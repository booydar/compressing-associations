"""Tests for huggingface_rmm_v4 and huggingface_rmm_v5.

Run from project root with FLA env:
    /cephfs/home/bulatov/envs/fla/bin/python -m pytest tests/test_rmm_v4_v5.py -v

or directly:
    /cephfs/home/bulatov/envs/fla/bin/python tests/test_rmm_v4_v5.py
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
    # Stub out pytest decorators so the file can be run as a plain script too.
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
        @staticmethod
        def raises(_exc, **__):
            class _Ctx:
                def __enter__(self_): return self_
                def __exit__(self_, et, ev, tb): return et is _exc or (et is not None and issubclass(et, _exc))
            return _Ctx()
    pytest = _PytestStub()
    _HAS_PYTEST = False

# Make project root importable when invoked from anywhere
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from modeling_rmt.huggingface_rmm_v2 import (
    RecurrentMemoryBase as RMMv2,
    RecurrentMemoryConfig as RMMv2Config,
)
from modeling_rmt.huggingface_rmm_v4 import (
    RecurrentMemoryBase as RMMv4,
    RecurrentMemoryConfig as RMMv4Config,
)
from modeling_rmt.huggingface_rmm_v5 import (
    RecurrentMemoryBase as RMMv5,
    RecurrentMemoryConfig as RMMv5Config,
)
from modeling_rmt.huggingface_rmm_v5 import (
    RecurrentMemoryLayerWrapper as V5Wrapper,
    MemoryWriter as V5MemoryWriter,
)


HIDDEN_SIZE = 64
N_HEADS = 1
HEAD_DIM = 32
N_LAYER = 2
VOCAB = 100
BATCH = 2
SEG_LEN = 5
N_SEG = 3
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _base_gpt2_config():
    cfg = AutoConfig.from_pretrained("gpt2")
    cfg.n_layer = N_LAYER
    cfg.n_head = N_HEADS
    cfg.n_embd = HIDDEN_SIZE
    cfg.vocab_size = VOCAB
    cfg.torch_dtype = "float32"
    return cfg


def _make_segments(n_seg=N_SEG, batch=BATCH, seg_len=SEG_LEN, seed=0):
    g = torch.Generator().manual_seed(seed)
    segs = []
    for _ in range(n_seg):
        ids = torch.randint(0, VOCAB, (batch, seg_len), generator=g)
        segs.append({
            "input_ids":      ids.to(DEVICE),
            "attention_mask": torch.ones(batch, seg_len, dtype=torch.long, device=DEVICE),
            "labels":         torch.full((batch, seg_len), -100, dtype=torch.long, device=DEVICE),
            "labels_mask":    torch.zeros(batch, seg_len, dtype=torch.bool, device=DEVICE),
        })
    return segs


def _seed_all(seed=0):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _build_v2():
    _seed_all(0)
    cfg = RMMv2Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        max_n_segments=10,
    )
    m = RMMv2(cfg).to(DEVICE).eval()
    return m


def _build_v4(write_mode, read_mode, write_value_dim=None, num_memory_vectors=1, num_memory_heads=1):
    _seed_all(0)
    cfg = RMMv4Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode=write_mode, read_mode=read_mode,
        num_memory_vectors=num_memory_vectors,
        write_value_dim=write_value_dim,
        num_memory_heads=num_memory_heads,
        max_n_segments=10,
    )
    m = RMMv4(cfg).to(DEVICE).eval()
    return m


def _build_v5(write_mode, read_mode, write_value_dim=None, num_memory_vectors=1,
              num_memory_heads=1, write_residual=False):
    _seed_all(0)
    cfg = RMMv5Config(
        base_model_config=_base_gpt2_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode=write_mode, read_mode=read_mode,
        num_memory_vectors=num_memory_vectors,
        write_value_dim=write_value_dim,
        num_memory_heads=num_memory_heads,
        write_residual=write_residual,
        max_n_segments=10,
    )
    m = RMMv5(cfg).to(DEVICE).eval()
    return m


# ---------------------------------------------------------------------------
# v4 tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v4_identity_equals_v2():
    """v4 identity/identity must produce identical logits to v2 (native GDN)."""
    segs = _make_segments()
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    m2 = _build_v2()
    m4 = _build_v4("identity", "identity")

    # Force identical weights for the shared subgraph.
    m4.load_state_dict(m2.state_dict(), strict=False)

    with torch.no_grad():
        out2 = m2(segments=copy.deepcopy(segs), labels=labels)
        out4 = m4(segments=copy.deepcopy(segs), labels=labels)

    diff = (out2.logits - out4.logits).abs().max().item()
    assert diff < 1e-4, f"v4 identity logits differ from v2 by {diff}"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
@pytest.mark.parametrize("write_mode,read_mode", [
    ("pool", "unpool"),
    ("cross_attn", "cross_attn"),
    ("pool", "cross_attn"),
    ("cross_attn", "unpool"),
])
def test_v4_shape_combinations(write_mode, read_mode):
    segs = _make_segments()
    labels = torch.cat([s["labels"] for s in segs], dim=1)
    m = _build_v4(write_mode, read_mode, num_memory_vectors=4, num_memory_heads=2)
    with torch.no_grad():
        out = m(segments=segs, labels=labels)
    assert out.logits.shape == (BATCH, N_SEG * SEG_LEN, VOCAB)


# ---------------------------------------------------------------------------
# v5 tests
# ---------------------------------------------------------------------------

def test_v5_init_fix_writer_query_scale():
    """write_queries should be initialised at std≈1/√d, not 0.02."""
    _seed_all(0)
    w = V5MemoryWriter(hidden_size=128, num_vectors=4, mode="cross_attn")
    s = w.write_queries.std().item()
    expected = 128 ** -0.5
    # allow ±25% noise around theoretical std for 4*128=512 samples
    assert 0.75 * expected < s < 1.25 * expected, (
        f"write_queries std={s:.4f}, expected ≈ {expected:.4f}"
    )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5_identity_equals_v2():
    segs = _make_segments()
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    m2 = _build_v2()
    m5 = _build_v5("identity", "identity")
    m5.load_state_dict(m2.state_dict(), strict=False)

    with torch.no_grad():
        out2 = m2(segments=copy.deepcopy(segs), labels=labels)
        out5 = m5(segments=copy.deepcopy(segs), labels=labels)

    diff = (out2.logits - out5.logits).abs().max().item()
    assert diff < 1e-4, f"v5 identity logits differ from v2 by {diff}"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5_gdn_readout_runs():
    """gdn_readout requires write_value_dim == hidden_size and runs end-to-end."""
    segs = _make_segments()
    labels = torch.cat([s["labels"] for s in segs], dim=1)
    m = _build_v5("cross_attn", "gdn_readout",
                  write_value_dim=HIDDEN_SIZE, num_memory_vectors=4)
    with torch.no_grad():
        out = m(segments=segs, labels=labels)
    assert out.logits.shape == (BATCH, N_SEG * SEG_LEN, VOCAB)
    assert torch.isfinite(out.logits).all()


def test_v5_gdn_readout_requires_matching_dim():
    """gdn_readout with mismatched dims should raise."""
    with pytest.raises(ValueError, match="gdn_readout"):
        _build_v5("cross_attn", "gdn_readout",
                  write_value_dim=HIDDEN_SIZE * 2, num_memory_vectors=4)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5_write_residual_changes_output():
    """write_residual=True should produce different logits than write_residual=False
    when other settings are identical."""
    segs = _make_segments()
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    m_off = _build_v5("cross_attn", "cross_attn", num_memory_vectors=4, write_residual=False)
    m_on  = _build_v5("cross_attn", "cross_attn", num_memory_vectors=4, write_residual=True)
    # Match weights (both seeds=0, but write_residual flag doesn't add params, so same dict)
    m_on.load_state_dict(m_off.state_dict(), strict=False)

    with torch.no_grad():
        o_off = m_off(segments=copy.deepcopy(segs), labels=labels).logits
        o_on  = m_on(segments=copy.deepcopy(segs),  labels=labels).logits

    diff = (o_off - o_on).abs().max().item()
    assert diff > 1e-4, f"write_residual=True did not change output (diff={diff})"


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5_gdn_readout_first_segment_no_residual():
    """On the very first segment, _gdn_readonly should return zeros (no prior state)."""
    m = _build_v5("cross_attn", "gdn_readout",
                  write_value_dim=HIDDEN_SIZE, num_memory_vectors=4)
    # Find one wrapper layer
    from modeling_rmt.huggingface_rmm_v5 import RecurrentMemoryCell
    layers = RecurrentMemoryCell._get_transformer_layers(m.rmt.memory_cell.model)
    w = layers[0]
    w.reset_memory()
    x = torch.randn(BATCH, SEG_LEN, HIDDEN_SIZE, device=DEVICE)
    out = w._gdn_readonly(x, attention_mask=None)
    assert torch.equal(out, torch.zeros_like(out))


# ---------------------------------------------------------------------------
# Runner segmenter test
# ---------------------------------------------------------------------------

def test_v5_runner_tokens_per_segment_split():
    """tokens_per_segment=1 splits a 12-token list into 12 single-token segments."""
    runner_path = os.path.join(_PROJECT_ROOT, "run_rmm_on_kv_retrieval-v5.py")
    # Load the segmenter via importlib to avoid invoking the script's __main__.
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_v5", runner_path)
    mod = importlib.util.module_from_spec(spec)
    # Skip executing module-level code that needs GPU envs by patching __name__
    # The runner guards heavy work with `if __name__ == '__main__'`, so import is safe.
    spec.loader.exec_module(mod)

    ids = list(range(12))
    one = mod.split_token_ids_into_segments(ids, tokens_per_segment=1)
    assert len(one) == 12
    assert all(len(s) == 1 for s in one)

    pair = mod.split_token_ids_into_segments(ids, tokens_per_segment=4)
    assert [len(s) for s in pair] == [4, 4, 4]

    none = mod.split_token_ids_into_segments(ids, tokens_per_segment=None)
    assert none == [ids]


if __name__ == "__main__":
    import traceback

    fns = [
        test_v5_init_fix_writer_query_scale,
        test_v5_gdn_readout_requires_matching_dim,
        test_v5_runner_tokens_per_segment_split,
    ]
    if torch.cuda.is_available():
        fns += [
            test_v4_identity_equals_v2,
            test_v5_identity_equals_v2,
            test_v5_gdn_readout_runs,
            test_v5_write_residual_changes_output,
            test_v5_gdn_readout_first_segment_no_residual,
        ]
        # parametrized v4 cases
        for wm, rm in [("pool", "unpool"), ("cross_attn", "cross_attn"),
                       ("pool", "cross_attn"), ("cross_attn", "unpool")]:
            def _wrap(wm=wm, rm=rm):
                return test_v4_shape_combinations(wm, rm)
            _wrap.__name__ = f"test_v4_shape_{wm}_{rm}"
            fns.append(_wrap)
    else:
        print("[warn] CUDA unavailable — skipping GDN tests")

    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)
