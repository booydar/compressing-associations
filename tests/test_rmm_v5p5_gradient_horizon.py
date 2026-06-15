"""Gradient-horizon tests for v5p5 identity-read.

Hypothesis: v5p5's state-pure identity read uses _snapshot_cache /
_restore_cache around the read pass. copy.deepcopy on a non-leaf tensor
raises, so the fallback path always runs — and the fallback does
``v.detach().clone()``, which severs the autograd graph. After restore,
the next segment's WRITE consumes a detached cache, so gradients cannot
backprop across more than one segment boundary through the write chain.

These tests:
  1. test_deepcopy_raises_on_non_leaf
     Pins the precondition: copy.deepcopy on a non-leaf tensor raises,
     so v5p5's fallback path is always taken in practice.
  2. test_snapshot_fallback_severs_autograd
     Isolated unit test of the snapshot/restore mechanism. Shows that
     .detach().clone() loses gradient, .clone() preserves it.
  3. test_v5p5_identity_read_gradient_horizon
     End-to-end: run RecurrentMemoryLayerWrapper on S segments
     recurrently, capture per-segment input gradients, and assert
     that early-segment inputs do NOT receive gradient from a loss on
     the last segment's output. This is what kills training at
     tps=1 / S>>1.

Run with FLA env:
    /home/bulatov/envs/fla/bin/python tests/test_rmm_v5p5_gradient_horizon.py
"""
import os
import sys
import copy
import torch
import torch.nn.functional as F

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    class _Skip:
        def __init__(self, *_, **__): pass
        def __call__(self, f): return f
    class _MarkNS:
        @staticmethod
        def skipif(*a, **kw): return _Skip()
    class _PytestStub:
        mark = _MarkNS()
    pytest = _PytestStub()
    _HAS_PYTEST = False

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ──────────────────────────────────────────────────────────────────────────
# 1) Pin precondition: deepcopy on non-leaf raises
# ──────────────────────────────────────────────────────────────────────────

def test_deepcopy_raises_on_non_leaf():
    """v5p5's _snapshot_cache tries copy.deepcopy(self.cache) and falls
    back on Exception. Since recurrent_state / conv_state coming out of
    a GDN forward are non-leaf tensors, deepcopy raises every time
    and the fallback path is always taken."""
    leaf = torch.randn(3, requires_grad=True)
    non_leaf = leaf * 2  # mimics a recurrent_state emerging from a forward
    assert not non_leaf.is_leaf and non_leaf.requires_grad

    raised = False
    try:
        copy.deepcopy(non_leaf)
    except RuntimeError as e:
        raised = True
        assert "graph leaves" in str(e), f"unexpected error: {e}"
    assert raised, "deepcopy on a non-leaf tensor was expected to raise"


# ──────────────────────────────────────────────────────────────────────────
# 2) Isolated unit test: fallback's .detach().clone() severs autograd
# ──────────────────────────────────────────────────────────────────────────

def _replicate_snapshot_restore(cache_tensor, use_detach):
    """Mimics v5p5's _gdn(read_only=True):
        snap = snapshot(self.cache)   # detach if use_detach else clone
        # ... read pass (omitted; doesn't affect this test) ...
        self.cache = snap             # _restore_cache
    Returns the "post-restore" tensor that the *next* WRITE call would
    consume as its input state.
    """
    if use_detach:
        return cache_tensor.detach().clone()   # current v5p5 fallback
    return cache_tensor.clone()                # proposed fix


def test_snapshot_fallback_severs_autograd():
    """The current fallback (`.detach().clone()`) loses backprop;
    `.clone()` would preserve it.

    We add a tiny ``+ 0 * dummy`` term so the loss always has a valid
    grad_fn; this lets us inspect ``early_input.grad`` (whose
    contribution through the snapshot path is what's actually under
    test) instead of crashing on a graph-less backward."""
    dummy = torch.zeros(1, requires_grad=True)  # keeps backward callable

    # ── buggy path: .detach().clone() ─────────────────────────────────
    early_input = torch.randn(4, requires_grad=True)
    # "write at segment s-1" produced this non-leaf state from early_input
    state_after_prev_write = early_input * 3.0
    assert not state_after_prev_write.is_leaf

    # v5p5's snapshot+restore replaces self.cache with detached copy
    restored_state = _replicate_snapshot_restore(state_after_prev_write, use_detach=True)
    assert restored_state.grad_fn is None, (
        "snapshot fallback should produce a detached tensor (no grad_fn); "
        f"got grad_fn={restored_state.grad_fn}"
    )

    # "write at segment s" consumes restored_state as its input state
    out = restored_state * 5.0
    loss = (out ** 2).sum() + 0.0 * dummy.sum()
    loss.backward()

    early_grad = early_input.grad
    assert early_grad is None or early_grad.abs().max().item() == 0.0, (
        "Expected zero gradient flow through the buggy snapshot path; "
        f"got grad-norm={early_grad.abs().max().item()}"
    )

    # ── fixed path: .clone() ──────────────────────────────────────────
    early_input2 = torch.randn(4, requires_grad=True)
    state2 = early_input2 * 3.0
    restored2 = _replicate_snapshot_restore(state2, use_detach=False)
    assert restored2.grad_fn is not None, (
        ".clone() should preserve grad_fn; got None"
    )
    out2 = restored2 * 5.0
    loss2 = (out2 ** 2).sum()
    loss2.backward()
    assert early_input2.grad is not None and early_input2.grad.abs().max().item() > 0.0, (
        "Expected non-zero gradient with .clone() (no detach); "
        f"got {early_input2.grad}"
    )


# ──────────────────────────────────────────────────────────────────────────
# 3) End-to-end: gradient horizon on actual RMM v5p5 layer
# ──────────────────────────────────────────────────────────────────────────

def _run_horizon_probe(n_layer, S=6, B=1, T=1, M=1):
    """Run a v5p5 model (write=pool, read=identity) over S segments
    recurrently and return per-segment first-layer-input gradient norms,
    where the loss depends only on segment S-1's logits.

    With the snapshot/restore detach bug, the gradient horizon through
    the per-layer write chain is ~1 segment, but each additional
    transformer layer opens one extra one-segment hop via that layer's
    own cache. Expected horizon ≈ n_layer + 1 non-zero tail segments;
    earlier segments should be exactly zero.
    """
    from transformers import AutoConfig
    from modeling_rmt.huggingface_rmm_v5p5 import (
        RecurrentMemoryBase as RMMv5p5,
        RecurrentMemoryConfig as RMMv5p5Config,
        RecurrentMemoryCell, RecurrentMemoryLayerWrapper,
    )

    torch.manual_seed(0)
    device = "cuda"

    base_cfg = AutoConfig.from_pretrained("gpt2")
    base_cfg.n_layer = n_layer; base_cfg.n_head = 1
    base_cfg.n_embd = 64; base_cfg.vocab_size = 100
    base_cfg.torch_dtype = "float32"

    rmm_cfg = RMMv5p5Config(
        base_model_config=base_cfg,
        fla_layer_name="GatedDeltaNet",
        num_heads=1, head_dim=32, expand_v=2.0, conv_size=4,
        write_mode='pool', read_mode='identity',
        num_memory_vectors=M,
        write_value_dim=None,
        num_memory_heads=1,
        use_parallel_prefill=False,   # force per-segment recurrent path
        max_n_segments=S + 4,
    )
    model = RMMv5p5(rmm_cfg).to(device).train()

    # Hook the first wrapped layer's INPUT hidden_states. retain_grad()
    # so we can read .grad on intermediate (non-leaf) tensors.
    layers = RecurrentMemoryCell._get_transformer_layers(model.rmt.memory_cell.model)
    first_wrapped = layers[0]
    assert isinstance(first_wrapped, RecurrentMemoryLayerWrapper)

    per_segment_inputs = []
    def pre_hook(_module, args, kwargs):
        hs = args[0] if args else kwargs.get('hidden_states')
        hs.retain_grad()
        per_segment_inputs.append(hs)
    handle = first_wrapped.register_forward_pre_hook(pre_hook, with_kwargs=True)

    # Build segments. Each segment is one token (T=1). Labels are
    # irrelevant — we don't use the model's masked-CE loss because its
    # shift-and-mask alignment doesn't let us isolate "loss only on
    # segment S-1's logits" cleanly. Instead we synthesize a loss from
    # the last segment's logits directly so the test is unambiguous.
    g = torch.Generator().manual_seed(1)
    segs = []
    for _ in range(S):
        segs.append({
            "input_ids": torch.randint(0, 100, (B, T), generator=g).to(device),
            "attention_mask": torch.ones(B, T, dtype=torch.long, device=device),
            "labels": torch.full((B, T), -100, dtype=torch.long, device=device),
            "labels_mask": torch.zeros(B, T, dtype=torch.bool, device=device),
        })
    labels = torch.cat([s["labels"] for s in segs], dim=1)

    out = model(segments=segs, labels=labels)
    try:
        handle.remove()
    except Exception:
        pass

    assert len(per_segment_inputs) == S, (
        f"expected {S} per-segment input captures, got {len(per_segment_inputs)}"
    )

    # Synthesize a loss that depends ONLY on segment S-1's logits.
    # full_logits is (B, S*T, V) concatenated in segment order.
    last_seg_logits = out.logits[:, -T:, :]
    loss = last_seg_logits.pow(2).sum()
    assert loss.requires_grad, "loss must be in the graph"
    loss.backward()

    grad_norms = [
        (hs.grad.norm().item() if hs.grad is not None else 0.0)
        for hs in per_segment_inputs
    ]
    return grad_norms


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5p5_identity_read_gradient_horizon_1layer():
    """Single-layer case: with one transformer layer, the per-layer
    write chain is the ONLY backprop route across segments. The
    snapshot/restore detach in _snapshot_cache truncates this chain at
    one hop, so segments 0..S-3 should have exactly zero gradient and
    only segments S-2 and S-1 should be non-zero."""
    S = 6
    grad_norms = _run_horizon_probe(n_layer=1, S=S)
    print(f"[1-layer] per-segment first-layer-input grad norms (S={S}): "
          f"{grad_norms}")

    # Sanity: last segment must receive gradient (loss is on its output).
    assert grad_norms[-1] > 0, (
        f"last-segment input must receive grad; got {grad_norms}"
    )

    # Bug signature.
    early = grad_norms[:-2]
    assert all(g == 0.0 for g in early), (
        f"Expected zero grad on segments 0..{S-3} (1-layer horizon = 1 "
        f"segment) due to detach in _snapshot_cache fallback; got "
        f"{grad_norms}.\nIf this assertion FAILS, the snapshot path "
        f"now preserves gradient — re-evaluate whether the bug is still "
        f"present."
    )

    # Segment S-2's write feeds the live (pre-restore) cache that
    # segment S-1's read consumes, so it does get non-zero gradient.
    assert grad_norms[-2] > 0, (
        f"Expected non-zero grad on segment {S-2} (one hop back); "
        f"got {grad_norms}"
    )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5p5_identity_read_gradient_horizon_scales_with_n_layer():
    """Cross-layer leakage diagnostic. Each extra transformer layer
    opens one additional one-segment hop, because layer k's read can
    pull gradient back through layer k-1's segment-output → layer k-1's
    read → layer k-1's live (pre-restore) cache. So with n_layer layers
    the effective horizon grows roughly to n_layer+1 — but for any
    fixed n_layer << S the horizon is still finite, far short of what
    tps=1 (S≈28) needs.

    This test pins the qualitative behaviour: with more layers, more
    tail segments become non-zero, but a prefix of early segments
    remains exactly zero."""
    S = 8
    norms_1 = _run_horizon_probe(n_layer=1, S=S)
    norms_2 = _run_horizon_probe(n_layer=2, S=S)
    print(f"[1-layer] (S={S}): {norms_1}")
    print(f"[2-layer] (S={S}): {norms_2}")

    def first_nonzero_from_end(xs):
        # Return the smallest k such that xs[-k:] are all > 0 and
        # xs[-(k+1)] == 0 (or k == len(xs)).
        n = len(xs)
        k = 0
        while k < n and xs[n - 1 - k] > 0:
            k += 1
        return k

    horizon_1 = first_nonzero_from_end(norms_1)
    horizon_2 = first_nonzero_from_end(norms_2)
    print(f"non-zero-tail length: 1-layer={horizon_1}, 2-layer={horizon_2}")

    # 1-layer: exactly 2 non-zero (S-1 and S-2). 2-layer: more.
    assert horizon_1 == 2, (
        f"1-layer horizon expected to be 2 segments; got {horizon_1} "
        f"({norms_1})"
    )
    assert horizon_2 > horizon_1, (
        f"adding a layer should extend the non-zero tail "
        f"(1L={horizon_1}, 2L={horizon_2})"
    )
    # And the very first segment must still be zero, even with 2 layers.
    assert norms_2[0] == 0.0, (
        f"segment 0 should still be unreachable with n_layer=2, "
        f"S={S}; got {norms_2}"
    )


if __name__ == "__main__":
    print("=== test_deepcopy_raises_on_non_leaf ===")
    test_deepcopy_raises_on_non_leaf()
    print("OK")

    print("\n=== test_snapshot_fallback_severs_autograd ===")
    test_snapshot_fallback_severs_autograd()
    print("OK")

    if torch.cuda.is_available():
        print("\n=== test_v5p5_identity_read_gradient_horizon_1layer ===")
        test_v5p5_identity_read_gradient_horizon_1layer()
        print("OK")

        print("\n=== test_v5p5_identity_read_gradient_horizon_scales_with_n_layer ===")
        test_v5p5_identity_read_gradient_horizon_scales_with_n_layer()
        print("OK")
    else:
        print("\n[skip] gradient_horizon tests require CUDA")

    print("\nAll gradient-horizon tests passed.")
