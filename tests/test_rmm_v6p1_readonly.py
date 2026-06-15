"""Read-only invariant for v6p0's ReadAwareGatedDeltaNet.

The core enabler of v6p0 is that 'read' tokens (read_mask=True) read the state
WITHOUT writing or decaying it. This pins three properties of the subclass:

  1. Reads don't modify the state: running reads-only on a fresh cache leaves
     recurrent_state at its initial (zero) value.
  2. Reads after writes don't touch the accumulated state: running reads on a
     cache that holds S_W leaves recurrent_state == S_W.
  3. Reads actually read the state (the valve isn't dead): the read output
     against a non-zero state S_W differs from the read output against the
     zero state, and reads placed *before* writes in one scan produce the same
     output as reads-only (they see the pre-write state S_{s-1}, not S_s).

Run with FLA env:
    /home/bulatov/envs/fla/bin/python -m pytest tests/test_rmm_v6p1_readonly.py -v
or:
    /home/bulatov/envs/fla/bin/python tests/test_rmm_v6p1_readonly.py
"""
import os
import sys

import torch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from modeling_rmt.huggingface_rmm_v6p1 import ReadAwareGatedDeltaNet
from fla.models.utils import Cache

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 64
HEAD_DIM = 32
NUM_HEADS = 1
R = 3   # read tokens
M = 5   # write tokens
B = 2
ATOL = 1e-5


def _build_gdn(seed=0):
    torch.manual_seed(seed)
    gdn = ReadAwareGatedDeltaNet(
        hidden_size=HIDDEN,
        expand_v=2.0,
        head_dim=HEAD_DIM,
        num_heads=NUM_HEADS,
        use_short_conv=True,
        conv_size=4,
        layer_idx=0,
    ).to(DEVICE).eval()
    return gdn


def _run(gdn, x, read_mask, cache=None):
    """One forward; returns (output, cache). Fresh cache if none given."""
    if cache is None:
        cache = Cache()
    out = gdn(x, attention_mask=None, past_key_values=cache,
              use_cache=True, read_mask=read_mask)
    return out[0], out[2]


def _state(cache):
    return cache[0]["recurrent_state"]


def _read_mask(n_read, n_write):
    m = torch.cat([
        torch.ones(n_read, dtype=torch.bool, device=DEVICE),
        torch.zeros(n_write, dtype=torch.bool, device=DEVICE),
    ])
    return m.unsqueeze(0).expand(B, -1)


def test_reads_do_not_modify_state():
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        return
    gdn = _build_gdn()
    reads = torch.randn(B, R, HIDDEN, device=DEVICE)

    # reads-only on a fresh cache -> state must stay at initial (zeros).
    _, cache = _run(gdn, reads, _read_mask(R, 0))
    S = _state(cache)
    assert torch.allclose(S, torch.zeros_like(S), atol=ATOL), (
        f"reads-only changed state: max|S|={S.abs().max().item():.3e}"
    )
    print("[1] reads-only leaves state at zero — OK")


def test_reads_after_writes_preserve_state():
    if not torch.cuda.is_available():
        return
    gdn = _build_gdn()
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    reads = torch.randn(B, R, HIDDEN, device=DEVICE)

    # Build a non-trivial state with writes.
    _, cache = _run(gdn, writes, _read_mask(0, M))
    S_W = _state(cache).clone()
    assert S_W.abs().max().item() > 1e-3, "writes produced a ~zero state; test is vacuous"

    # Now run reads on the same cache — state must be unchanged.
    _, cache = _run(gdn, reads, _read_mask(R, 0), cache=cache)
    S_after = _state(cache)
    assert torch.allclose(S_after, S_W, atol=ATOL), (
        f"reads modified accumulated state: max diff={ (S_after-S_W).abs().max().item():.3e}"
    )
    print("[2] reads after writes preserve accumulated state — OK")


def test_reads_actually_read_state():
    if not torch.cuda.is_available():
        return
    gdn = _build_gdn()
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    reads = torch.randn(B, R, HIDDEN, device=DEVICE)

    # read against zero state
    out_zero, _ = _run(gdn, reads, _read_mask(R, 0))

    # read against S_W (write first into a fresh cache, then read)
    _, cache = _run(gdn, writes, _read_mask(0, M))
    out_afterW, _ = _run(gdn, reads, _read_mask(R, 0), cache=cache)

    diff = (out_zero - out_afterW).abs().max().item()
    assert diff > 1e-4, f"read output ignores state (diff={diff:.3e}) — valve is dead"
    print(f"[3] reads reflect state (diff={diff:.3e}) — OK")


def test_reads_first_see_pre_write_state():
    """Reads placed before writes in ONE scan read S_{s-1}, i.e. their output
    equals reads-only output (writes are causally after the reads)."""
    if not torch.cuda.is_available():
        return
    gdn = _build_gdn()
    reads = torch.randn(B, R, HIDDEN, device=DEVICE)
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)

    # reads-only
    out_reads_only, _ = _run(gdn, reads, _read_mask(R, 0))

    # [reads, writes] in one scan; read outputs are the first R rows
    x = torch.cat([reads, writes], dim=1)
    out_both, _ = _run(gdn, x, _read_mask(R, M))
    out_reads_in_scan = out_both[:, :R]

    diff = (out_reads_only - out_reads_in_scan).abs().max().item()
    assert torch.allclose(out_reads_only, out_reads_in_scan, atol=ATOL), (
        f"reads-first do not match reads-only (diff={diff:.3e}); "
        f"reads are contaminated by trailing writes"
    )
    print(f"[4] reads-first read pre-write state (diff={diff:.3e}) — OK")


if __name__ == "__main__":
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        sys.exit(0)
    test_reads_do_not_modify_state()
    test_reads_after_writes_preserve_state()
    test_reads_actually_read_state()
    test_reads_first_see_pre_write_state()
    print("\nAll read-only invariant tests passed.")
