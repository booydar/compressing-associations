"""Equivalence tests for v5p7_eff (the O(L^2)-free parallel prefill).

v5p7_eff must be the SAME MODEL as v5p7 — same parameters in the same places,
same forward function — with only the memory layout of the parallel path
changed (segments folded into the batch dim instead of masked block-diagonally).
So there are three things to prove, in increasing strength:

  1. internal consistency:   eff parallel  == eff recurrent
  2. cross-module identity:  eff           == v5p7, both forms, same weights
  3. the opt-in streaming paths agree with the default path on loss, and on
     predictions at the positions that carry labels

Plus a padded-batch case, because folding turns v5p7's additive 4-D pad mask
into a (B*S, T) 2-D mask and that path deserves its own coverage.

Run with the FLA env:
    ~/envs/fla/bin/python -m pytest tests/test_rmm_v5p7_eff_equivalence.py -v
or:
    ~/envs/fla/bin/python tests/test_rmm_v5p7_eff_equivalence.py
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

from modeling_rmt.huggingface_rmm_v5p7 import (
    RecurrentMemoryBase as RMMv5p7,
    RecurrentMemoryConfig as RMMv5p7Config,
)
from modeling_rmt.huggingface_rmm_v5p7_eff import (
    RecurrentMemoryBase as RMMEff,
    RecurrentMemoryConfig as RMMEffConfig,
)

HIDDEN_SIZE = 64
N_HEADS = 1
HEAD_DIM = 32
N_LAYER = 2
VOCAB = 100
BATCH = 2
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# GDN's parallel scan vs sequential calls drift by a few ulps in fp32 (reduction
# order), and folding also changes which SDPA kernel runs. Same headroom the
# other equivalence suites use.
ATOL_FP32 = 1e-3
RTOL_FP32 = 1e-3

_SKIP = pytest.mark.skipif(not torch.cuda.is_available(),
                           reason="GDN Triton kernels need CUDA")


def _base_gpt2_config():
    cfg = AutoConfig.from_pretrained("gpt2")
    cfg.n_layer = N_LAYER
    cfg.n_head = N_HEADS
    cfg.n_embd = HIDDEN_SIZE
    cfg.vocab_size = VOCAB
    cfg.torch_dtype = "float32"
    # Dropout off: the backward comparison runs in train() mode, and two models
    # drawing their own dropout masks would differ for reasons that have nothing
    # to do with the fold.
    cfg.resid_pdrop = cfg.embd_pdrop = cfg.attn_pdrop = 0.0
    return cfg


def _base_llama_config():
    """Llama exercises the position_embeddings / cache_position re-folding that
    GPT-2 (absolute learned positions) never touches."""
    cfg = AutoConfig.from_pretrained("NousResearch/Llama-3.2-1B")
    cfg.num_hidden_layers = N_LAYER
    cfg.num_attention_heads = N_HEADS
    cfg.num_key_value_heads = N_HEADS
    cfg.hidden_size = HIDDEN_SIZE
    cfg.head_dim = HIDDEN_SIZE // N_HEADS
    cfg.intermediate_size = HIDDEN_SIZE * 2
    cfg.vocab_size = VOCAB
    cfg.torch_dtype = "float32"
    return cfg


def _seed_all(seed=0):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _make_segments(n_seg, seg_len, batch=BATCH, seed=0, label_last=False,
                   pad_last_rows=0):
    """Context segments carry no labels; only the final (QT) segment does when
    label_last=True — the layout both streaming paths assume.

    pad_last_rows>0 zeroes the attention_mask on the tail of the CONTEXT
    segments for that many batch rows, to exercise the 2-D pad-mask path."""
    g = torch.Generator().manual_seed(seed)
    segs = []
    for i in range(n_seg):
        ids = torch.randint(0, VOCAB, (batch, seg_len), generator=g)
        am = torch.ones(batch, seg_len, dtype=torch.long)
        is_qt = (i == n_seg - 1)
        if pad_last_rows and not is_qt and seg_len > 1:
            am[:pad_last_rows, -1] = 0
        if is_qt and label_last:
            labels = ids.clone()
            lmask = torch.ones(batch, seg_len, dtype=torch.bool)
        else:
            labels = torch.full((batch, seg_len), -100, dtype=torch.long)
            lmask = torch.zeros(batch, seg_len, dtype=torch.bool)
        segs.append({
            "input_ids": ids.to(DEVICE),
            "attention_mask": am.to(DEVICE),
            "labels": labels.to(DEVICE),
            "labels_mask": lmask.to(DEVICE),
        })
    return segs


def _build(module, write_mode, read_mode, num_memory_vectors=1,
           write_value_dim=None, num_memory_heads=1, use_parallel_prefill=True,
           base="gpt2", **extra):
    cls, cfg_cls = ((RMMEff, RMMEffConfig) if module == "eff"
                    else (RMMv5p7, RMMv5p7Config))
    _seed_all(0)
    cfg = cfg_cls(
        base_model_config=_base_gpt2_config() if base == "gpt2" else _base_llama_config(),
        fla_layer_name="GatedDeltaNet",
        num_heads=N_HEADS, head_dim=HEAD_DIM,
        expand_v=2.0, conv_size=4,
        write_mode=write_mode, read_mode=read_mode,
        num_memory_vectors=num_memory_vectors,
        write_value_dim=write_value_dim,
        num_memory_heads=num_memory_heads,
        use_parallel_prefill=use_parallel_prefill,
        max_n_segments=10,
        **extra,
    )
    return cls(cfg).to(DEVICE).eval()


def _run(model, segs, parallel):
    model.set_parallel_prefill(parallel)
    with torch.no_grad():
        return model(segments=copy.deepcopy(segs),
                     labels=torch.cat([s["labels"] for s in segs], dim=1))


# --------------------------------------------------------------------------- #
# 1. eff parallel == eff recurrent                                             #
# --------------------------------------------------------------------------- #

@_SKIP
@pytest.mark.parametrize("write_mode,read_mode,M,T,S", [
    ('identity',   'identity', 4, 4, 3),
    ('cross_attn', 'cross_attn', 1, 1, 4),
    ('cross_attn', 'cross_attn', 4, 4, 3),
    ('cross_attn', 'cross_attn', 4, 8, 3),
    ('pool',       'unpool',   4, 4, 3),
])
def test_eff_parallel_equals_recurrent(write_mode, read_mode, M, T, S):
    segs = _make_segments(n_seg=S + 1, seg_len=T)
    m = _build("eff", write_mode, read_mode, num_memory_vectors=M)
    p, r = _run(m, segs, True), _run(m, segs, False)
    diff = (p.logits - r.logits).abs().max().item()
    assert torch.allclose(p.logits, r.logits, rtol=RTOL_FP32, atol=ATOL_FP32), (
        f"eff parallel vs recurrent differ by max={diff} "
        f"({write_mode}/{read_mode}, M={M}, T={T}, S={S})")
    print(f"eff par==rec {write_mode}/{read_mode} M={M} T={T} S={S}: {diff:.2e}")


@_SKIP
def test_eff_parallel_equals_recurrent_llama():
    """Llama backbone: covers position_embeddings + cache_position re-folding."""
    segs = _make_segments(n_seg=4, seg_len=4)
    m = _build("eff", 'pool', 'unpool', num_memory_vectors=4, base="llama")
    p, r = _run(m, segs, True), _run(m, segs, False)
    diff = (p.logits - r.logits).abs().max().item()
    assert torch.allclose(p.logits, r.logits, rtol=RTOL_FP32, atol=ATOL_FP32), \
        f"llama eff parallel vs recurrent differ by max={diff}"
    print(f"eff par==rec llama: {diff:.2e}")


@_SKIP
@pytest.mark.parametrize("base", ["gpt2", "llama"])
def test_folded_row_chunking(base="gpt2"):
    """B*S above MAX_FOLD_ROWS must chunk, and change nothing.

    Folding puts B*S in a CUDA grid dimension, which is capped at 65535 — hit for
    real at tps=7 / N=16384 pairs / B=8 (B*S = 131064), where the un-chunked call
    dies with 'invalid configuration argument'. Rather than build a 131k-row case
    here, we shrink the threshold so a small model takes the same code path."""
    from modeling_rmt.huggingface_rmm_v5p7_eff import RecurrentMemoryLayerWrapper

    segs = _make_segments(n_seg=9, seg_len=4)          # B*S = 2*8 = 16 folded rows
    m = _build("eff", 'pool', 'unpool', num_memory_vectors=4, base=base)

    ref = _run(m, segs, True)
    prev = RecurrentMemoryLayerWrapper.MAX_FOLD_ROWS
    RecurrentMemoryLayerWrapper.MAX_FOLD_ROWS = 3      # force several chunks
    try:
        chunked = _run(m, segs, True)
    finally:
        RecurrentMemoryLayerWrapper.MAX_FOLD_ROWS = prev

    diff = (ref.logits - chunked.logits).abs().max().item()
    assert torch.allclose(ref.logits, chunked.logits, rtol=RTOL_FP32, atol=ATOL_FP32), \
        f"row chunking changed the result ({base}): max diff {diff}"
    print(f"folded row chunking {base}: {diff:.2e}")


@_SKIP
def test_eff_parallel_equals_recurrent_padded():
    """Padded context: v5p7's additive 4-D mask becomes a (B*S, T) 2-D mask."""
    segs = _make_segments(n_seg=4, seg_len=4, pad_last_rows=1)
    m = _build("eff", 'pool', 'unpool', num_memory_vectors=4)
    p, r = _run(m, segs, True), _run(m, segs, False)
    diff = (p.logits - r.logits).abs().max().item()
    assert torch.allclose(p.logits, r.logits, rtol=RTOL_FP32, atol=ATOL_FP32), \
        f"padded eff parallel vs recurrent differ by max={diff}"
    print(f"eff par==rec padded: {diff:.2e}")


# --------------------------------------------------------------------------- #
# 2. eff == v5p7                                                               #
# --------------------------------------------------------------------------- #

@_SKIP
@pytest.mark.parametrize("write_mode,read_mode,M,T,S,base", [
    ('identity',   'identity', 4, 4, 3, "gpt2"),
    ('cross_attn', 'cross_attn', 4, 4, 3, "gpt2"),
    ('pool',       'unpool',   4, 4, 3, "gpt2"),
    ('pool',       'unpool',   4, 4, 3, "llama"),
])
def test_eff_matches_v5p7(write_mode, read_mode, M, T, S, base="gpt2"):
    """Same seed -> same weights; both modules must produce the same logits in
    both execution forms. This is what makes v5p7 checkpoints reusable."""
    segs = _make_segments(n_seg=S + 1, seg_len=T)
    old = _build("v5p7", write_mode, read_mode, num_memory_vectors=M, base=base)
    new = _build("eff", write_mode, read_mode, num_memory_vectors=M, base=base)

    # Belt and braces: identical seeds should already give identical weights,
    # but copy them across so a construction-order change can't silently pass.
    new.load_state_dict(old.state_dict(), strict=True)

    for parallel in (True, False):
        a, b = _run(old, segs, parallel), _run(new, segs, parallel)
        diff = (a.logits - b.logits).abs().max().item()
        assert torch.allclose(a.logits, b.logits, rtol=RTOL_FP32, atol=ATOL_FP32), (
            f"v5p7 vs eff differ by max={diff} "
            f"(parallel={parallel}, {base}, {write_mode}/{read_mode}, M={M}, T={T}, S={S})")
        print(f"eff==v5p7 {base} parallel={parallel} {write_mode}/{read_mode}: {diff:.2e}")


@_SKIP
def test_eff_matches_v5p7_grads():
    """Gradients must match too — the fold changes the SDPA kernel, not the
    function, so backward has to agree within the same tolerance."""
    segs = _make_segments(n_seg=4, seg_len=4, label_last=True)
    labels = torch.cat([s["labels"] for s in segs], dim=1)
    old = _build("v5p7", 'pool', 'unpool', num_memory_vectors=4)
    new = _build("eff", 'pool', 'unpool', num_memory_vectors=4)
    new.load_state_dict(old.state_dict(), strict=True)

    grads = []
    for m in (old, new):
        m.train()
        m.zero_grad(set_to_none=True)
        m(segments=copy.deepcopy(segs), labels=labels).loss.backward()
        grads.append({k: v.grad.detach().clone()
                      for k, v in m.named_parameters() if v.grad is not None})

    assert grads[0].keys() == grads[1].keys(), "parameter sets differ"
    worst, worst_k = 0.0, None
    for k in grads[0]:
        d = (grads[0][k] - grads[1][k]).abs().max().item()
        if d > worst:
            worst, worst_k = d, k
    assert worst < ATOL_FP32, f"grad mismatch max={worst} at {worst_k}"
    print(f"eff==v5p7 grads: max {worst:.2e} at {worst_k}")


# --------------------------------------------------------------------------- #
# 3. opt-in streaming paths                                                    #
# --------------------------------------------------------------------------- #

@_SKIP
@pytest.mark.parametrize("flag,parallel,base", [
    ("stream_context_logits", True,  "gpt2"),
    ("stream_context_logits", True,  "llama"),   # different headless-backbone attr
    ("eval_stream_logits",    False, "gpt2"),
])
def test_streaming_paths_match_default(flag, parallel, base="gpt2"):
    """Streaming returns (B, L) int predictions instead of float logits. Loss
    must be identical, and the predictions must match argmax of the default
    path everywhere (not just at labelled positions)."""
    segs = _make_segments(n_seg=4, seg_len=4, label_last=True)
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    ref = _build("eff", 'pool', 'unpool', num_memory_vectors=4, base=base)
    stream = _build("eff", 'pool', 'unpool', num_memory_vectors=4, base=base,
                    **{flag: True})
    stream.load_state_dict(ref.state_dict(), strict=True)

    ref.set_parallel_prefill(parallel)
    stream.set_parallel_prefill(parallel)
    with torch.no_grad():
        a = ref(segments=copy.deepcopy(segs), labels=labels)
        b = stream(segments=copy.deepcopy(segs), labels=labels)

    assert b.logits.dim() == 2, f"{flag} must return 2-D int predictions"
    assert b.logits.shape == a.logits.shape[:2], \
        f"{flag} prediction shape {tuple(b.logits.shape)} != {tuple(a.logits.shape[:2])}"
    assert torch.equal(a.logits.argmax(dim=-1), b.logits), f"{flag} predictions differ"
    ld = (a.loss - b.loss).abs().item()
    assert ld < ATOL_FP32, f"{flag} loss differs by {ld}"
    print(f"{flag} ({base}, parallel={parallel}): loss diff {ld:.2e}, predictions identical")


@_SKIP
def test_stream_context_logits_rejects_labelled_context():
    """The path is only exact when the context is fully masked — misuse must
    raise, not silently drop loss terms."""
    segs = _make_segments(n_seg=4, seg_len=4, label_last=True)
    segs[0]["labels_mask"][:] = True
    m = _build("eff", 'pool', 'unpool', num_memory_vectors=4,
               stream_context_logits=True)
    labels = torch.cat([s["labels"] for s in segs], dim=1)
    try:
        with torch.no_grad():
            m(segments=segs, labels=labels)
    except RuntimeError as e:
        assert "labels only in the final segment" in str(e)
        print("stream_context_logits correctly rejected a labelled context")
        return
    raise AssertionError("expected RuntimeError for labelled context segment")


if __name__ == "__main__":
    if not torch.cuda.is_available():
        print("CUDA not available — GDN Triton kernels require it. Skipping.")
        sys.exit(0)

    def _run_maybe_parametrized(fn):
        vals = getattr(fn, "_param_values", None)
        if vals is None:
            print(f"=== {fn.__name__} ===")
            fn()
        else:
            for v in vals:
                args = v if isinstance(v, tuple) else (v,)
                print(f"=== {fn.__name__}{args} ===")
                fn(*args)

    for f in (test_eff_parallel_equals_recurrent,
              test_eff_parallel_equals_recurrent_llama,
              test_folded_row_chunking,
              test_eff_parallel_equals_recurrent_padded,
              test_eff_matches_v5p7,
              test_eff_matches_v5p7_grads,
              test_streaming_paths_match_default,
              test_stream_context_logits_rejects_labelled_context):
        _run_maybe_parametrized(f)

    print("\nAll v5p7_eff equivalence tests passed.")
