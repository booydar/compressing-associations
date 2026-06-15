"""Smoke tests for modeling_fla — Stage 3 conv-substitution.

Three tests, mirroring the design doc:

  1. **Equivalence** — with ``binder_kind=passthrough``, the
     ``GatedDeltaNetBinder`` / ``Mamba2Binder`` block reproduces the upstream
     FLA layer to 1e-5 (or 1e-3 in bf16).
  2. **Bypass sanity** — with ``binder_kind=none``, the block runs without
     error and is *not* equal to passthrough (the conv slot really is gone).
  3. **Window-matched** — with ``binder_kind=swa, binder_window=1``, output
     is close to ``none`` within seed noise (a 1-wide causal window can only
     attend to the current token, so SWA reduces to a per-token linear map
     ≈ identity-ish; we just check it doesn't blow up).

Run with the FLA env:

    /cephfs/home/bulatov/envs/fla/bin/python -m pytest \\
        tests/test_modeling_fla_binder.py -v
"""
from __future__ import annotations

import os
import sys

import torch

# Allow `python tests/test_modeling_fla_binder.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False

try:
    from fla.layers.gated_deltanet import GatedDeltaNet
    from fla.layers.mamba2 import Mamba2
    _HAS_FLA = True
except ImportError:
    _HAS_FLA = False

if _HAS_FLA:
    from modeling_fla import GatedDeltaNetBinder, Mamba2Binder


HIDDEN = 64
HEADS = 4
HEAD_DIM = 16
CONV = 4
SEQ = 32
BATCH = 2


def _set_seed(s: int = 0):
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


def _copy_state(src: torch.nn.Module, dst: torch.nn.Module) -> None:
    """Copy params/buffers that exist with matching shapes in both modules.
    Used to make a binder-wrapped layer match the weights of an upstream
    layer so we can compare forwards directly.
    """
    src_sd = dict(src.state_dict())
    dst_sd = dict(dst.state_dict())
    new = {}
    for k, v in dst_sd.items():
        if k in src_sd and src_sd[k].shape == v.shape:
            new[k] = src_sd[k]
        else:
            new[k] = v
    dst.load_state_dict(new, strict=False)


def _build_gdn_pair():
    """Build an upstream FLA GDN layer and a passthrough-mode binder layer
    with weight-copied conv modules, ready for an equivalence check.
    """
    _set_seed(0)
    ref = GatedDeltaNet(
        hidden_size=HIDDEN, num_heads=HEADS, head_dim=HEAD_DIM,
        conv_size=CONV, use_short_conv=True, use_gate=True,
        layer_idx=0,
    )
    _set_seed(0)
    layer = GatedDeltaNetBinder(
        hidden_size=HIDDEN, num_heads=HEADS, head_dim=HEAD_DIM,
        conv_size=CONV, use_short_conv=True, use_gate=True,
        layer_idx=0, binder_kind="passthrough",
    )
    # In passthrough mode the binder wraps the ORIGINAL ShortConvolution
    # built by super().__init__ — same seed → same weights at construction.
    # Still, copy state to be defensive against any RNG-consuming code
    # added by the binder constructor between the two seedings.
    _copy_state(ref, layer)
    return ref, layer


def _build_m2_pair():
    _set_seed(0)
    ref = Mamba2(
        num_heads=HEADS, head_dim=HEAD_DIM, hidden_size=HIDDEN,
        state_size=16, expand=1, n_groups=1, conv_kernel=CONV,
        layer_idx=0,
    )
    _set_seed(0)
    layer = Mamba2Binder(
        num_heads=HEADS, head_dim=HEAD_DIM, hidden_size=HIDDEN,
        state_size=16, expand=1, n_groups=1, conv_kernel=CONV,
        layer_idx=0, binder_kind="passthrough",
    )
    _copy_state(ref, layer)
    return ref, layer


# ---------- Test 1: equivalence (passthrough ≡ upstream FLA) ----------

skip_if_no_fla = (
    pytest.mark.skipif(not _HAS_FLA, reason="fla not installed")
    if _HAS_PYTEST else (lambda f: f)
)


@skip_if_no_fla
def test_gdn_passthrough_equivalence():
    ref, layer = _build_gdn_pair()
    ref.eval(); layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)

    with torch.no_grad():
        y_ref, _, _ = ref(x)
        y_new, _, _ = layer(x)
    assert y_ref.shape == y_new.shape
    diff = (y_ref - y_new).abs().max().item()
    assert diff < 1e-5, f"GDN passthrough drift {diff} > 1e-5"


@skip_if_no_fla
def test_mamba2_passthrough_equivalence():
    ref, layer = _build_m2_pair()
    ref.eval(); layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y_ref, _, _ = ref(x)
        y_new, _, _ = layer(x)
    assert y_ref.shape == y_new.shape
    diff = (y_ref - y_new).abs().max().item()
    # Mamba2 may take a slightly different forward path on CPU (torch_forward
    # in both cases) — still expect tight equivalence.
    assert diff < 1e-5, f"Mamba2 passthrough drift {diff} > 1e-5"


# ---------- Test 2: bypass sanity (none runs, differs from passthrough) ----------

@skip_if_no_fla
def test_gdn_none_runs_and_differs():
    _set_seed(0)
    ref, _ = _build_gdn_pair()
    _set_seed(0)
    layer = GatedDeltaNetBinder(
        hidden_size=HIDDEN, num_heads=HEADS, head_dim=HEAD_DIM,
        conv_size=CONV, use_short_conv=True, use_gate=True,
        layer_idx=0, binder_kind="none",
    )
    _copy_state(ref, layer)
    ref.eval(); layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y_ref, _, _ = ref(x)
        y_new, _, _ = layer(x)
    assert torch.isfinite(y_new).all()
    diff = (y_ref - y_new).abs().max().item()
    # The whole point: removing the conv must change the output.
    assert diff > 1e-3, f"GDN none was suspiciously close to passthrough: {diff}"


@skip_if_no_fla
def test_mamba2_none_runs_and_differs():
    _set_seed(0)
    ref, _ = _build_m2_pair()
    _set_seed(0)
    layer = Mamba2Binder(
        num_heads=HEADS, head_dim=HEAD_DIM, hidden_size=HIDDEN,
        state_size=16, expand=1, n_groups=1, conv_kernel=CONV,
        layer_idx=0, binder_kind="none",
    )
    _copy_state(ref, layer)
    ref.eval(); layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y_ref, _, _ = ref(x)
        y_new, _, _ = layer(x)
    assert torch.isfinite(y_new).all()
    diff = (y_ref - y_new).abs().max().item()
    assert diff > 1e-3, f"Mamba2 none was suspiciously close to passthrough: {diff}"


# ---------- Test 3: window-1 SWA runs and stays finite ----------

@skip_if_no_fla
def test_gdn_swa_window1_runs():
    layer = GatedDeltaNetBinder(
        hidden_size=HIDDEN, num_heads=HEADS, head_dim=HEAD_DIM,
        conv_size=CONV, use_short_conv=True, use_gate=True,
        layer_idx=0, binder_kind="swa", binder_window=1, binder_n_heads=1,
    )
    layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y, _, _ = layer(x)
    assert torch.isfinite(y).all()


@skip_if_no_fla
def test_gdn_swa_window4_with_rank_runs():
    layer = GatedDeltaNetBinder(
        hidden_size=HIDDEN, num_heads=HEADS, head_dim=HEAD_DIM,
        conv_size=CONV, use_short_conv=True, use_gate=True,
        layer_idx=0, binder_kind="swa", binder_window=4,
        binder_n_heads=1, binder_rank=4,
    )
    layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y, _, _ = layer(x)
    assert torch.isfinite(y).all()


@skip_if_no_fla
def test_mamba2_swa_window4_runs():
    layer = Mamba2Binder(
        num_heads=HEADS, head_dim=HEAD_DIM, hidden_size=HIDDEN,
        state_size=16, expand=1, n_groups=1, conv_kernel=CONV,
        layer_idx=0, binder_kind="swa", binder_window=4, binder_n_heads=1,
    )
    layer.eval()
    x = torch.randn(BATCH, SEQ, HIDDEN)
    with torch.no_grad():
        y, _, _ = layer(x)
    assert torch.isfinite(y).all()


# ---------- Standalone runner ----------

if __name__ == "__main__":
    if not _HAS_FLA:
        print("SKIP: fla is not importable in this environment.")
        sys.exit(0)
    failures = 0
    tests = [
        test_gdn_passthrough_equivalence,
        test_mamba2_passthrough_equivalence,
        test_gdn_none_runs_and_differs,
        test_mamba2_none_runs_and_differs,
        test_gdn_swa_window1_runs,
        test_gdn_swa_window4_with_rank_runs,
        test_mamba2_swa_window4_runs,
    ]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    sys.exit(1 if failures else 0)
