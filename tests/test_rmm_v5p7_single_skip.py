"""Single-skip + equivalence tests for v5p7.

v5p7 fixes the per-layer double-residual bug v5p4 had via
``RecurrentLayerWithSkip``. The structural invariant these tests pin down:

  Exactly ONE additive skip per layer, at the call site:
    identity:  out_h = post_attn + GDN(LN_f(post_attn))
    pool/xa:   out_h = post_attn + decompress(LN_r(post_attn), prev_mem)

Tests in this file:

  1. ``test_no_with_skip_class_in_module`` — purely structural; no GPU. Asserts
     ``RecurrentLayerWithSkip`` was deleted (or at least is never used) so the
     bug class cannot regress silently.

  2. ``test_identity_zero_gdn_is_passthrough`` — with ``base_layer`` replaced
     by passthrough and GDN's output projection zeroed, identity-mode wrapper
     output must equal input exactly. Catches any extra additive term on the
     residual stream.

  3. ``test_pool_zero_decompress_is_passthrough`` — same idea for pool branch:
     base=passthrough, decompress output zeroed → wrapper out == input.

  4. ``test_v5p4_v5p7_differ_by_lnf_post_attn`` — regression vs v5p4. Builds
     both with identical fla-layer weights, identity mode, GDN output zeroed,
     and verifies ``v5p4_out - v5p7_out`` equals ``LN_f(post_attn)`` on a
     single layer (the term v5p7 removed).

  5. Equivalence tests (parallel ≡ recurrent) — ported from v5p4. Run on CUDA.

Run with FLA env:
    ~/envs/fla/bin/python -m pytest tests/test_rmm_v5p7_single_skip.py -v
or:
    ~/envs/fla/bin/python tests/test_rmm_v5p7_single_skip.py
"""
import os
import sys
import copy
import torch
import torch.nn as nn
from transformers import AutoConfig

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    class _SkipMark:
        def __init__(self, *_, **__): pass
        def __call__(self, f): return f
    class _ParamMark:
        def __init__(self, _spec, _values): self._values = _values
        def __call__(self, f):
            f._param_values = self._values
            return f
    class _MarkNS:
        @staticmethod
        def skipif(*a, **kw): return _SkipMark()
        @staticmethod
        def parametrize(spec, values): return _ParamMark(spec, values)
    class _PytestStub:
        mark = _MarkNS()
    pytest = _PytestStub()
    _HAS_PYTEST = False

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import modeling_rmt.huggingface_rmm_v5p7 as v5p7_mod
from modeling_rmt.huggingface_rmm_v5p7 import (
    RecurrentMemoryBase as RMMv5p7,
    RecurrentMemoryConfig as RMMv5p7Config,
    RecurrentMemoryLayerWrapper as Wrapper7,
)

HIDDEN_SIZE = 64
N_HEADS = 1
HEAD_DIM = 32
N_LAYER = 2
VOCAB = 100
BATCH = 2
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

ATOL_FP32 = 1e-3
RTOL_FP32 = 1e-3


def _base_gpt2_config():
    cfg = AutoConfig.from_pretrained("gpt2")
    cfg.n_layer = N_LAYER
    cfg.n_head = N_HEADS
    cfg.n_embd = HIDDEN_SIZE
    cfg.vocab_size = VOCAB
    cfg.torch_dtype = "float32"
    return cfg


def _seed_all(seed=0):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ─────────────────────────────────────────────────────────────────────────────
# Structural invariant: WithSkip is gone
# ─────────────────────────────────────────────────────────────────────────────

def test_no_with_skip_class_in_module():
    """v5p7 must not define RecurrentLayerWithSkip. If someone re-adds it,
    this test fails immediately — no GPU needed."""
    assert not hasattr(v5p7_mod, "RecurrentLayerWithSkip"), (
        "v5p7 must not define RecurrentLayerWithSkip. The single-skip "
        "invariant is enforced by call-site residual only."
    )


def test_no_with_skip_in_constructed_model():
    """Build a model on CPU (skip GDN forward) and verify no submodule has a
    name containing 'WithSkip' or behaves like input+output wrapping."""
    cfg = RMMv5p7Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode='identity', read_mode='identity',
        num_memory_vectors=1, max_n_segments=10,
    )
    _seed_all(0)
    # Construct on CPU is fine — we only inspect parameters/types.
    m = RMMv5p7(cfg)
    bad = [n for n, _ in m.named_modules() if "WithSkip" in type(_).__name__]
    assert not bad, f"unexpected WithSkip-typed modules: {bad}"


# ─────────────────────────────────────────────────────────────────────────────
# Behavioral invariant: zero-out GDN/decompress, base=passthrough → out == in
# ─────────────────────────────────────────────────────────────────────────────

class _PassthroughBase(nn.Module):
    """Stands in for a Llama decoder layer. Returns (hidden_states,) so
    output[0] == hidden_states regardless of any kwargs."""
    def forward(self, hidden_states, *args, **kwargs):
        return (hidden_states,)


def _zero_gdn_output_proj(gdn):
    """Zero GDN's output projection. Guarantees GDN(x) == 0 for any x,
    regardless of internal init (gating, A_log, etc.) — multiplying anything
    by a zero output matrix gives zero."""
    with torch.no_grad():
        gdn.o_proj.weight.zero_()
        if getattr(gdn.o_proj, "bias", None) is not None:
            gdn.o_proj.bias.zero_()


def _zero_decompress_output(decompress):
    with torch.no_grad():
        if decompress.mode == 'unpool':
            decompress.v_proj.weight.zero_()
            if decompress.v_proj.bias is not None:
                decompress.v_proj.bias.zero_()
        else:  # cross_attn
            decompress.cross_attn.o_proj.weight.zero_()
            if decompress.cross_attn.o_proj.bias is not None:
                decompress.cross_attn.o_proj.bias.zero_()


def _build_layer_wrapper(write_mode, read_mode, num_memory_vectors=1):
    """Build a single RecurrentMemoryLayerWrapper directly, with a passthrough
    base and a real (raw) GDN. Bypasses the full RMM build path."""
    _seed_all(0)
    import fla.layers as fla_layers
    gdn = fla_layers.GatedDeltaNet(
        hidden_size=HIDDEN_SIZE, layer_idx=0,
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4, use_short_conv=True,
    )
    base = _PassthroughBase()
    wrapper = Wrapper7(
        base_layer=base,
        fla_layer=gdn,
        model_hidden_size=HIDDEN_SIZE,
        num_memory_vectors=num_memory_vectors,
        write_mode=write_mode, read_mode=read_mode,
        write_value_dim=None, num_memory_heads=1,
    )
    return wrapper, gdn


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_identity_zero_gdn_is_passthrough():
    """Identity branch, GDN zeroed: out_h must equal x exactly.

    v5p7 formula: out_h = post_attn + GDN(LN_f(post_attn))
                        = x         + 0                    = x.

    v5p4 would fail this test: out_h = x + LN_f(x) + 0 = x + LN_f(x) ≠ x.
    """
    wrapper, gdn = _build_layer_wrapper('identity', 'identity', num_memory_vectors=1)
    wrapper = wrapper.to(DEVICE).eval()
    _zero_gdn_output_proj(gdn)

    _seed_all(1)
    T = 8
    x = torch.randn(BATCH, T, HIDDEN_SIZE, device=DEVICE)
    with torch.no_grad():
        out = wrapper(x)
    out_t = out[0] if isinstance(out, tuple) else out
    diff = (out_t - x).abs().max().item()
    assert torch.allclose(out_t, x, atol=ATOL_FP32, rtol=RTOL_FP32), (
        f"identity zero-GDN should be passthrough; max diff = {diff:.3e}"
    )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("write_mode,read_mode", [
    ('pool', 'unpool'),
    ('cross_attn', 'cross_attn'),
])
def test_pool_zero_decompress_is_passthrough(write_mode, read_mode):
    """Pool / cross_attn branch with decompress output zeroed: out_h == x.

    v5p7 formula: out_h = post_attn + decompress(LN_r(post_attn), prev_mem)
                        = x         + 0                                    = x.
    """
    M = 4
    wrapper, gdn = _build_layer_wrapper(write_mode, read_mode, num_memory_vectors=M)
    wrapper = wrapper.to(DEVICE).eval()
    _zero_decompress_output(wrapper.decompress)

    _seed_all(1)
    T = 8
    x = torch.randn(BATCH, T, HIDDEN_SIZE, device=DEVICE)
    with torch.no_grad():
        out = wrapper(x)
    out_t = out[0] if isinstance(out, tuple) else out
    diff = (out_t - x).abs().max().item()
    assert torch.allclose(out_t, x, atol=ATOL_FP32, rtol=RTOL_FP32), (
        f"{write_mode}/{read_mode} zero-decompress should be passthrough; "
        f"max diff = {diff:.3e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regression: v5p4 vs v5p7 differ by exactly LN_f(post_attn) per layer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5p4_v5p7_differ_by_lnf_post_attn():
    """With GDN output zeroed and passthrough base, identity-mode v5p4
    output is exactly ``x + fla_norm(x)`` and v5p7 output is exactly ``x``.
    So ``v5p4 - v5p7 == fla_norm(x)`` — that's the bug v5p7 removed."""
    try:
        import modeling_rmt.huggingface_rmm_v5p4 as v5p4_mod
        from modeling_rmt.huggingface_rmm_v5p4 import (
            RecurrentMemoryLayerWrapper as Wrapper4,
            RecurrentLayerWithSkip as WithSkip4,
        )
    except ImportError:
        pytest.skip("v5p4 not present; nothing to diff against")
        return

    # Build v5p7 wrapper.
    w7, g7 = _build_layer_wrapper('identity', 'identity')
    w7 = w7.to(DEVICE).eval()
    _zero_gdn_output_proj(g7)

    # Build v5p4 wrapper with the same GDN init wrapped in WithSkip.
    _seed_all(0)
    import fla.layers as fla_layers
    g4 = fla_layers.GatedDeltaNet(
        hidden_size=HIDDEN_SIZE, layer_idx=0,
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4, use_short_conv=True,
    )
    _zero_gdn_output_proj(g4)
    wrapped_gdn = WithSkip4(g4)
    base4 = _PassthroughBase()
    w4 = Wrapper4(
        base_layer=base4, fla_layer=wrapped_gdn,
        model_hidden_size=HIDDEN_SIZE,
        num_memory_vectors=1,
        write_mode='identity', read_mode='identity',
        write_value_dim=None, num_memory_heads=1,
    ).to(DEVICE).eval()
    # Copy fla_norm weight so both wrappers normalize identically.
    with torch.no_grad():
        w4.fla_norm.weight.copy_(w7.fla_norm.weight)

    _seed_all(2)
    T = 8
    x = torch.randn(BATCH, T, HIDDEN_SIZE, device=DEVICE)
    with torch.no_grad():
        out7 = w7(x)
        out4 = w4(x)
        expected_diff = w7.fla_norm(x)
    o7 = out7[0] if isinstance(out7, tuple) else out7
    o4 = out4[0] if isinstance(out4, tuple) else out4
    actual_diff = o4 - o7
    err = (actual_diff - expected_diff).abs().max().item()
    assert torch.allclose(actual_diff, expected_diff, atol=ATOL_FP32, rtol=RTOL_FP32), (
        f"v5p4 - v5p7 should equal fla_norm(x); max err = {err:.3e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Equivalence: parallel ≡ recurrent (ported from v5p4 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _make_segments(n_seg, seg_len, batch=BATCH, seed=0):
    g = torch.Generator().manual_seed(seed)
    segs = []
    for _ in range(n_seg):
        ids = torch.randint(0, VOCAB, (batch, seg_len), generator=g)
        segs.append({
            "input_ids": ids.to(DEVICE),
            "attention_mask": torch.ones(batch, seg_len, dtype=torch.long, device=DEVICE),
            "labels": torch.full((batch, seg_len), -100, dtype=torch.long, device=DEVICE),
            "labels_mask": torch.zeros(batch, seg_len, dtype=torch.bool, device=DEVICE),
        })
    return segs


def _build_full(write_mode, read_mode, M=1, **kwargs):
    _seed_all(0)
    cfg = RMMv5p7Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode=write_mode, read_mode=read_mode,
        num_memory_vectors=M, max_n_segments=10,
        **kwargs,
    )
    return RMMv5p7(cfg).to(DEVICE).eval()


def _compare_parallel_vs_recurrent(write_mode, read_mode, M, T, S=3, **kwargs):
    segs = _make_segments(n_seg=S + 1, seg_len=T)
    labels = torch.cat([s["labels"] for s in segs], dim=1)
    m = _build_full(write_mode, read_mode, M=M, **kwargs)

    m.set_parallel_prefill(True)
    with torch.no_grad():
        out_p = m(segments=copy.deepcopy(segs), labels=labels)
    m.set_parallel_prefill(False)
    with torch.no_grad():
        out_r = m(segments=copy.deepcopy(segs), labels=labels)
    diff = (out_p.logits - out_r.logits).abs().max().item()
    assert torch.allclose(out_p.logits, out_r.logits, rtol=RTOL_FP32, atol=ATOL_FP32), (
        f"parallel vs recurrent differ by max={diff} "
        f"(write={write_mode}, read={read_mode}, M={M}, T={T}, S={S})"
    )
    return diff


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_identity_equivalence():
    diff = _compare_parallel_vs_recurrent('identity', 'identity', M=4, T=4, S=3)
    print(f"identity diff = {diff:.2e}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [(1, 4, 3), (4, 4, 3), (4, 8, 3)])
def test_cross_attn_equivalence(M, T, S):
    diff = _compare_parallel_vs_recurrent('cross_attn', 'cross_attn', M=M, T=T, S=S)
    print(f"cross_attn M={M} T={T} S={S} diff = {diff:.2e}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [(1, 4, 3), (4, 4, 3)])
def test_pool_unpool_equivalence(M, T, S):
    diff = _compare_parallel_vs_recurrent('pool', 'unpool', M=M, T=T, S=S)
    print(f"pool/unpool M={M} T={T} S={S} diff = {diff:.2e}")


if __name__ == "__main__":
    print("=== test_no_with_skip_class_in_module ===")
    test_no_with_skip_class_in_module()
    print("OK")

    print("\n=== test_no_with_skip_in_constructed_model ===")
    test_no_with_skip_in_constructed_model()
    print("OK")

    if not torch.cuda.is_available():
        print("\nCUDA unavailable — skipping GDN-dependent tests.")
        sys.exit(0)

    print("\n=== test_identity_zero_gdn_is_passthrough ===")
    test_identity_zero_gdn_is_passthrough()
    print("OK")

    print("\n=== test_pool_zero_decompress_is_passthrough(pool/unpool) ===")
    test_pool_zero_decompress_is_passthrough('pool', 'unpool')
    print("OK")
    print("\n=== test_pool_zero_decompress_is_passthrough(cross_attn) ===")
    test_pool_zero_decompress_is_passthrough('cross_attn', 'cross_attn')
    print("OK")

    print("\n=== test_v5p4_v5p7_differ_by_lnf_post_attn ===")
    test_v5p4_v5p7_differ_by_lnf_post_attn()
    print("OK")

    print("\n=== test_identity_equivalence ===")
    test_identity_equivalence()
    print("OK")

    print("\n=== test_cross_attn_equivalence ===")
    for M, T, S in [(1, 4, 3), (4, 4, 3), (4, 8, 3)]:
        test_cross_attn_equivalence(M, T, S)
    print("OK")

    print("\n=== test_pool_unpool_equivalence ===")
    for M, T, S in [(1, 4, 3), (4, 4, 3)]:
        test_pool_unpool_equivalence(M, T, S)
    print("OK")

    print("\nALL TESTS PASSED")
