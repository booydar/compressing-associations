"""Write-state invariance to read content — the regression that pins v6p1.

v6p1 splits the identity-read segment into two GDN calls: a read on a throwaway
fork of the recurrent state (``_gdn_read``) and a write on the persistent cache
(``_gdn_write``). The whole point is that the read can no longer leak into the
write through the in-place ``Cache`` / causal short conv. This test pins exactly
that property:

    Given a fixed pre-segment state S_{s-1} and fixed write vectors, the
    recurrent_state AFTER the write must be bit-identical regardless of what the
    read tokens were.

Under v6p0's single ``[reads, writes]`` scan this fails: the reads sit in the
write tokens' causal conv shadow, so changing the reads changes the write k/v
and therefore S_s. Under v6p1 it holds by construction — and this test guards
against anyone collapsing the two calls back into one.

The helpers under test (``_gdn_read`` / ``_gdn_write`` / ``_read_state_cache``)
only touch ``self.fla_layer`` and ``self.cache``, so we exercise the REAL
methods bound to a lightweight shim rather than standing up a full base model.

Run with FLA env:
    /home/bulatov/envs/fla/bin/python tests/test_rmm_v6p1_write_invariance.py
"""
import os
import sys

import torch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from modeling_rmt.huggingface_rmm_v6p1 import (
    ReadAwareGatedDeltaNet,
    RecurrentMemoryLayerWrapper as W,
)
from fla.models.utils import Cache

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 64
HEAD_DIM = 32
NUM_HEADS = 1
T = 6   # read tokens (the post-attn tokens, in identity read)
M = 5   # write vectors
B = 2
ATOL = 1e-6


def _build_gdn(seed=0):
    torch.manual_seed(seed)
    return ReadAwareGatedDeltaNet(
        hidden_size=HIDDEN,
        expand_v=2.0,
        head_dim=HEAD_DIM,
        num_heads=NUM_HEADS,
        use_short_conv=True,
        conv_size=4,
        layer_idx=0,
    ).to(DEVICE).eval()


class _Shim:
    """Minimal carrier of the attributes the helpers use, with the REAL helper
    methods (incl. ``_read_state_cache``, which ``_gdn_read`` calls) bound onto
    it so we exercise the actual v6p1 code path."""
    def __init__(self, gdn):
        self.fla_layer = gdn
        self.cache = Cache()
        self._read_state_cache = W._read_state_cache.__get__(self)


def _bind(shim):
    return (
        W._gdn_read.__get__(shim),
        W._gdn_write.__get__(shim),
    )


def _state(cache):
    return cache[0]["recurrent_state"]


def _segment(shim, writes_ctx, reads, writes_seg):
    """Fresh cache -> seed S_{s-1} with writes_ctx -> read -> write. Returns
    (read_output, recurrent_state_after_write)."""
    shim.cache = Cache()
    read, write = _bind(shim)
    write(writes_ctx)                      # establish S_{s-1} (deterministic)
    g = read(reads)                        # read on a fork; must not touch cache
    write(writes_seg)                      # S_{s-1} -> S_s on persistent cache
    return g, _state(shim.cache).clone()


def test_write_state_invariant_to_reads():
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        return
    gdn = _build_gdn()
    shim = _Shim(gdn)

    torch.manual_seed(1)
    writes_ctx = torch.randn(B, M, HIDDEN, device=DEVICE)   # builds S_{s-1}
    writes_seg = torch.randn(B, M, HIDDEN, device=DEVICE)   # the segment's write
    reads_A = torch.randn(B, T, HIDDEN, device=DEVICE)
    reads_B = torch.randn(B, T, HIDDEN, device=DEVICE)      # different read content

    g_A, S_A = _segment(shim, writes_ctx, reads_A, writes_seg)
    g_B, S_B = _segment(shim, writes_ctx, reads_B, writes_seg)

    # Non-vacuous: the two reads really do produce different read outputs.
    read_diff = (g_A - g_B).abs().max().item()
    assert read_diff > 1e-4, (
        f"reads_A and reads_B gave the same read output (diff={read_diff:.3e}); "
        f"test is vacuous"
    )

    # The pin: write-resulting state is identical despite different reads.
    state_diff = (S_A - S_B).abs().max().item()
    assert state_diff <= ATOL, (
        f"write state leaked read content: max diff={state_diff:.3e} "
        f"(reads differed by {read_diff:.3e}). The read is contaminating the "
        f"write — the split is broken."
    )
    print(f"[1] write state invariant to read content "
          f"(state diff={state_diff:.3e}, read diff={read_diff:.3e}) — OK")


def test_read_does_not_mutate_persistent_cache():
    """Directly: a read leaves self.cache's recurrent_state untouched."""
    if not torch.cuda.is_available():
        return
    gdn = _build_gdn()
    shim = _Shim(gdn)
    read, write = _bind(shim)

    torch.manual_seed(2)
    writes_ctx = torch.randn(B, M, HIDDEN, device=DEVICE)
    reads = torch.randn(B, T, HIDDEN, device=DEVICE)

    write(writes_ctx)
    S_before = _state(shim.cache).clone()
    assert S_before.abs().max().item() > 1e-3, "seed state ~zero; test vacuous"

    for _ in range(3):                     # repeated reads must all be no-ops
        read(reads)
    S_after = _state(shim.cache)

    diff = (S_after - S_before).abs().max().item()
    assert diff <= ATOL, f"read mutated persistent cache: diff={diff:.3e}"
    print(f"[2] read leaves persistent cache untouched (diff={diff:.3e}) — OK")


if __name__ == "__main__":
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        sys.exit(0)
    test_write_state_invariant_to_reads()
    test_read_does_not_mutate_persistent_cache()
    print("\nAll write-invariance tests passed.")
