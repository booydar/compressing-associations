"""Pure-PyTorch tests for the LocalBinder primitives — no FLA needed.

These exercise the SWA / none / passthrough paths and the
ShortConvBinder / Conv1dBinder adapter signatures. They run anywhere
torch is importable so we can sanity-check the design without spinning up
the full FLA env.

    python tests/test_local_binder.py
"""
from __future__ import annotations

import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modeling_fla.local_binder import (  # noqa: E402
    Conv1dBinder,
    LocalBinderCore,
    ShortConvBinder,
    _SWA,
)


def _allclose(a, b, tol=1e-6):
    return (a - b).abs().max().item() < tol


def test_swa_window1_is_per_token():
    torch.manual_seed(0)
    swa = _SWA(hidden_size=8, window=1, n_heads=1)
    x = torch.randn(2, 5, 8)
    y = swa(x)
    # With window=1, position t can only attend to itself, so softmax over
    # a single element is 1.0 → y_t = O · V_t = O · (V_proj · x_t). The map
    # is purely token-wise; permuting the time axis must permute the output
    # identically.
    perm = torch.tensor([3, 1, 0, 4, 2])
    y_perm = swa(x[:, perm, :])
    assert _allclose(y[:, perm, :], y_perm, tol=1e-5)


def test_swa_causality():
    torch.manual_seed(0)
    swa = _SWA(hidden_size=8, window=4, n_heads=2)
    x = torch.randn(1, 6, 8)
    y_full = swa(x)
    # Zero the future after position 2; the output at positions <=2 must
    # not change. (Causal masking should make later tokens irrelevant.)
    x2 = x.clone()
    x2[:, 3:, :] = 99.0
    y_trunc = swa(x2)
    assert _allclose(y_full[:, :3, :], y_trunc[:, :3, :], tol=1e-5)


def test_local_binder_core_none_passes_through_with_activation():
    core = LocalBinderCore(hidden_size=4, kind="none", window=4,
                           activation="silu")
    x = torch.randn(2, 5, 4)
    y = core(x)
    assert torch.allclose(y, torch.nn.functional.silu(x))


def test_short_conv_binder_signature_none():
    binder = ShortConvBinder(
        hidden_size=4, conv_size=4, kind="none",
        fallback=None, activation="silu",
    )
    x = torch.randn(2, 5, 4)
    out, cache = binder(x=x, cache=None, output_final_state=False, cu_seqlens=None)
    assert out.shape == x.shape
    assert cache is None


def test_conv1d_binder_shape_none():
    binder = Conv1dBinder(
        conv_dim=4, conv_kernel=4, kind="none", fallback=None,
    )
    x = torch.randn(2, 4, 7)  # [B, D, T]
    y = binder(x)
    assert y.shape == x.shape


def test_short_conv_binder_passthrough_delegates():
    class Recorder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.called_with = None

        def forward(self, x, cache=None, output_final_state=False,
                    cu_seqlens=None):
            self.called_with = (x.shape, cache, output_final_state, cu_seqlens)
            return x * 2, "STATE"

    rec = Recorder()
    binder = ShortConvBinder(
        hidden_size=4, conv_size=4, kind="passthrough", fallback=rec,
    )
    x = torch.randn(1, 3, 4)
    out, state = binder(x=x, cache=None, output_final_state=True,
                        cu_seqlens=None)
    assert state == "STATE"
    assert torch.allclose(out, x * 2)
    assert rec.called_with[0] == x.shape


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}: {e!r}")
            except Exception as e:
                fails += 1
                print(f"ERR   {name}: {e!r}")
    sys.exit(1 if fails else 0)
