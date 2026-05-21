"""Gradient-horizon REGRESSION tests for v5p6.

v5p6 replaced v5p5's snapshot/restore around the identity read with a
non-mutating cache fork that uses ``.clone()`` (preserves autograd)
instead of ``.detach().clone()``. These tests assert the fix actually
works: with v5p6, every prior segment's input must receive gradient
from a loss on the final segment's output.

Companion to ``tests/test_rmm_v5p5_gradient_horizon.py``, which pins
the v5p5 bug signature (gradient horizon ≈ n_layer+1).

Run with FLA env:
    /home/bulatov/envs/fla/bin/python tests/test_rmm_v5p6_gradient_horizon.py
"""
import os
import sys
import torch

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


def _run_horizon_probe(n_layer, S=6, B=1, T=1, M=1):
    """Run a v5p6 model (write=pool, read=identity) over S segments
    recurrently and return per-segment first-layer-input gradient norms,
    where the loss depends only on segment S-1's logits."""
    from transformers import AutoConfig
    from modeling_rmt.huggingface_rmm_v5p6 import (
        RecurrentMemoryBase as RMMv5p6,
        RecurrentMemoryConfig as RMMv5p6Config,
        RecurrentMemoryCell, RecurrentMemoryLayerWrapper,
    )

    torch.manual_seed(0)
    device = "cuda"

    base_cfg = AutoConfig.from_pretrained("gpt2")
    base_cfg.n_layer = n_layer; base_cfg.n_head = 1
    base_cfg.n_embd = 64; base_cfg.vocab_size = 100
    base_cfg.torch_dtype = "float32"

    rmm_cfg = RMMv5p6Config(
        base_model_config=base_cfg,
        fla_layer_name="GatedDeltaNet",
        num_heads=1, head_dim=32, expand_v=2.0, conv_size=4,
        write_mode='pool', read_mode='identity',
        num_memory_vectors=M,
        write_value_dim=None,
        num_memory_heads=1,
        use_parallel_prefill=False,
        max_n_segments=S + 4,
    )
    model = RMMv5p6(rmm_cfg).to(device).train()

    layers = RecurrentMemoryCell._get_transformer_layers(model.rmt.memory_cell.model)
    first_wrapped = layers[0]
    assert isinstance(first_wrapped, RecurrentMemoryLayerWrapper)

    per_segment_inputs = []
    def pre_hook(_module, args, kwargs):
        hs = args[0] if args else kwargs.get('hidden_states')
        hs.retain_grad()
        per_segment_inputs.append(hs)
    handle = first_wrapped.register_forward_pre_hook(pre_hook, with_kwargs=True)

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

    last_seg_logits = out.logits[:, -T:, :]
    loss = last_seg_logits.pow(2).sum()
    assert loss.requires_grad, "loss must be in the graph"
    loss.backward()

    return [
        (hs.grad.norm().item() if hs.grad is not None else 0.0)
        for hs in per_segment_inputs
    ]


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5p6_full_gradient_horizon_1layer():
    """1 transformer layer, S=6 segments. With the fork-based fix every
    segment's input must receive gradient from a loss on segment S-1."""
    S = 6
    grad_norms = _run_horizon_probe(n_layer=1, S=S)
    print(f"[1-layer] per-segment first-layer-input grad norms (S={S}): "
          f"{grad_norms}")

    assert grad_norms[-1] > 0, f"sanity: last segment must get grad, got {grad_norms}"

    for s, g in enumerate(grad_norms):
        assert g > 0, (
            f"v5p6 regression: segment {s}'s input received zero grad "
            f"(grad norms = {grad_norms}). Fork-based read should give "
            f"full S-segment horizon — if any are zero, autograd is "
            f"still being severed somewhere in _fork_cache / _gdn."
        )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="GDN Triton kernels need CUDA")
def test_v5p6_full_gradient_horizon_4layers():
    """Production-like setting: n_layer=4 (matches the assoc-comp-rmm
    runs), S=8 segments. Every segment must still receive gradient."""
    S = 8
    grad_norms = _run_horizon_probe(n_layer=4, S=S)
    print(f"[4-layer] per-segment first-layer-input grad norms (S={S}): "
          f"{grad_norms}")

    for s, g in enumerate(grad_norms):
        assert g > 0, (
            f"v5p6 regression: segment {s}'s input received zero grad "
            f"(grad norms = {grad_norms})."
        )


if __name__ == "__main__":
    if not torch.cuda.is_available():
        print("CUDA not available — skipping.")
        sys.exit(0)

    print("=== test_v5p6_full_gradient_horizon_1layer ===")
    test_v5p6_full_gradient_horizon_1layer()
    print("OK")

    print("\n=== test_v5p6_full_gradient_horizon_4layers ===")
    test_v5p6_full_gradient_horizon_4layers()
    print("OK")

    print("\nAll v5p6 gradient-horizon regression tests passed.")
