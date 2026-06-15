"""Equivalence tests for v5p5.

v5p5 adds a state-pure identity-read mode that decouples read from write.
Tests assert parallel ≡ recurrent across all supported (write, read) combos:
  * write=pool,       read=unpool      (v5p4 behavior, regression guard)
  * write=pool,       read=cross_attn  (v5p4 behavior)
  * write=cross_attn, read=cross_attn  (v5p4 behavior)
  * write=identity,   read=identity    (v5p4 behavior)
  * write=pool,       read=identity    (NEW)
  * write=cross_attn, read=identity    (NEW)

Run with FLA env:
    /cephfs/home/bulatov/envs/fla/bin/python -m pytest tests/test_rmm_v5p5_equivalence.py -v
or:
    /cephfs/home/bulatov/envs/fla/bin/python tests/test_rmm_v5p5_equivalence.py
"""
import os
import sys
import copy
import torch
from transformers import AutoConfig

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    class _SkipMark:
        def __init__(self, *_, **__): pass
        def __call__(self, f): return f
    class _ParamMark:
        def __init__(self, _spec, _values):
            self._values = _values
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

from modeling_rmt.huggingface_rmm_v5p5 import (
    RecurrentMemoryBase as RMMv5p5,
    RecurrentMemoryConfig as RMMv5p5Config,
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


def _build(write_mode, read_mode, num_memory_vectors=1,
           write_value_dim=None, num_memory_heads=1, use_parallel_prefill=True):
    _seed_all(0)
    cfg = RMMv5p5Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode=write_mode, read_mode=read_mode,
        num_memory_vectors=num_memory_vectors,
        write_value_dim=write_value_dim,
        num_memory_heads=num_memory_heads,
        use_parallel_prefill=use_parallel_prefill,
        max_n_segments=10,
    )
    m = RMMv5p5(cfg).to(DEVICE).eval()
    return m


def _compare(write_mode, read_mode, M, T, S=4, **kwargs):
    """Build one model, run twice — once with parallel prefill, once recurrent —
    and assert logits match."""
    segs = _make_segments(n_seg=S + 1, seg_len=T)
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    m = _build(write_mode, read_mode, num_memory_vectors=M, **kwargs)

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


# ── v5p4 regression-guard cases ────────────────────────────────────────────

@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_identity_equivalence():
    """write=identity, read=identity: unchanged v5p4 path."""
    T = 4
    diff = _compare(write_mode='identity', read_mode='identity', M=T, T=T, S=3)
    print(f"identity diff = {diff:.2e}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [
    (1, 1, 4),
    (1, 4, 3),
    (4, 4, 3),
])
def test_cross_attn_equivalence(M, T, S):
    """write=cross_attn, read=cross_attn: parallel == recurrent."""
    diff = _compare(write_mode='cross_attn', read_mode='cross_attn',
                    M=M, T=T, S=S, num_memory_heads=1)
    print(f"cross_attn M={M} T={T} S={S} diff = {diff:.2e}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [
    (1, 4, 3),
    (4, 4, 3),
])
def test_pool_unpool_equivalence(M, T, S):
    """write=pool, read=unpool: parallel == recurrent."""
    diff = _compare(write_mode='pool', read_mode='unpool', M=M, T=T, S=S)
    print(f"pool/unpool M={M} T={T} S={S} diff = {diff:.2e}")


# ── NEW: identity-read combos ──────────────────────────────────────────────

@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [
    (1, 1, 4),
    (1, 4, 3),
    (2, 7, 3),
    (4, 4, 3),
])
def test_pool_identity_equivalence(M, T, S):
    """write=pool, read=identity (NEW): parallel == recurrent."""
    diff = _compare(write_mode='pool', read_mode='identity', M=M, T=T, S=S)
    print(f"pool/identity M={M} T={T} S={S} diff = {diff:.2e}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("M,T,S", [
    (1, 1, 4),
    (1, 4, 3),
    (4, 4, 3),
])
def test_cross_attn_identity_equivalence(M, T, S):
    """write=cross_attn, read=identity (NEW): parallel == recurrent."""
    diff = _compare(write_mode='cross_attn', read_mode='identity',
                    M=M, T=T, S=S, num_memory_heads=1)
    print(f"cross_attn/identity M={M} T={T} S={S} diff = {diff:.2e}")


if __name__ == "__main__":
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        sys.exit(0)

    print("=== test_identity_equivalence ===")
    test_identity_equivalence()
    print("OK")

    print("\n=== test_cross_attn_equivalence ===")
    for M, T, S in [(1, 1, 4), (1, 4, 3), (4, 4, 3)]:
        test_cross_attn_equivalence(M, T, S)
    print("OK")

    print("\n=== test_pool_unpool_equivalence ===")
    for M, T, S in [(1, 4, 3), (4, 4, 3)]:
        test_pool_unpool_equivalence(M, T, S)
    print("OK")

    print("\n=== test_pool_identity_equivalence ===")
    for M, T, S in [(1, 1, 4), (1, 4, 3), (2, 7, 3), (4, 4, 3)]:
        test_pool_identity_equivalence(M, T, S)
    print("OK")

    print("\n=== test_cross_attn_identity_equivalence ===")
    for M, T, S in [(1, 1, 4), (1, 4, 3), (4, 4, 3)]:
        test_cross_attn_identity_equivalence(M, T, S)
    print("OK")

    print("\nAll equivalence tests passed.")
