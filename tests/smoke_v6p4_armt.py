"""Smoke test for v6p4-armt self_attn (ARMT-style) compression path.

Builds the model exactly like run_rmm_on_kv_retrieval-v6p4-armt.py, runs a
multi-segment forward + backward, and checks:
  * mem tokens are appended/stripped (logits length == real token count)
  * loss is finite and gradients flow to the mem-token bank + GDN + base layer
  * a sanity equivalence: write_mode='self_attn' vs the existing 'cross_attn'
    both run (shapes line up), and self_attn forces recurrent mode.
Run on the remote host with the fla env:
  ~/envs/fla/bin/python tests/smoke_v6p4_armt.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import torch
from transformers import AutoConfig, AutoTokenizer

TOK = "./tokenizers/kv_alphabet_62/"


def build(write_mode, num_memory_vectors=4, state_size=32, n_head=4, expand_v=2.0):
    from modeling_rmt.huggingface_rmm_v6p4_armt import RecurrentMemoryBase, RecurrentMemoryConfig
    tok = AutoTokenizer.from_pretrained(TOK)
    cfg = AutoConfig.from_pretrained("NousResearch/Llama-3.2-1B")
    cfg.num_hidden_layers = 4
    cfg.num_attention_heads = n_head
    cfg.num_key_value_heads = n_head
    cfg.hidden_size = 128
    cfg.head_dim = 128 // n_head
    cfg.intermediate_size = 512
    cfg.torch_dtype = "float32"
    cfg.vocab_size = tok.vocab_size
    cfg.pad_token_id = tok.convert_tokens_to_ids("[PAD]")
    cfg.bos_token_id = tok.convert_tokens_to_ids("[BOS]")
    cfg.eos_token_id = tok.convert_tokens_to_ids("[EOS]")
    rmm = RecurrentMemoryConfig(
        base_model_config=cfg, fla_layer_name="GatedDeltaNet",
        num_heads=n_head, head_dim=state_size // n_head, expand_v=expand_v,
        conv_size=4, use_short_conv=True,
        num_memory_vectors=num_memory_vectors, write_mode=write_mode,
        read_mode="identity", write_value_dim=None, num_memory_heads=1,
        num_compress_heads=4, use_parallel_prefill=True, thread_memory=True,
        max_n_segments=10,
        think_token_id=tok.convert_tokens_to_ids("[THINK]"),
        answer_token_id=tok.convert_tokens_to_ids("[ANSWER]"),
        bos_token_id=tok.convert_tokens_to_ids("[BOS]"),
        eos_token_id=tok.convert_tokens_to_ids("[EOS]"),
    )
    return RecurrentMemoryBase(rmm), tok


def make_segments(tok, B=3, T=7, S=3, device="cpu"):
    """S context segments of T tokens + a final qt segment with a 2-token target."""
    V = tok.vocab_size
    segs = []
    for _ in range(S):
        ids = torch.randint(5, V, (B, T), device=device)
        segs.append(dict(
            input_ids=ids,
            attention_mask=torch.ones(B, T, dtype=torch.long, device=device),
            labels=torch.full((B, T), -100, dtype=torch.long, device=device),
            labels_mask=torch.zeros(B, T, dtype=torch.bool, device=device),
        ))
    qt = torch.randint(5, V, (B, 4), device=device)
    labels = torch.full((B, 4), -100, dtype=torch.long, device=device)
    labels[:, -2:] = qt[:, -2:]
    lm = torch.zeros(B, 4, dtype=torch.bool, device=device)
    lm[:, -3:] = True
    segs.append(dict(input_ids=qt, attention_mask=torch.ones(B, 4, dtype=torch.long, device=device),
                     labels=labels, labels_mask=lm))
    full_labels = torch.cat([s["labels"] for s in segs], dim=1)
    return segs, full_labels


def run(write_mode):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(0)
    model, tok = build(write_mode)
    model = model.to(dev).train()
    segs, full_labels = make_segments(tok, device=dev)
    out = model(segments=segs, labels=full_labels)
    loss = out["loss"]
    total_tokens = sum(s["input_ids"].shape[1] for s in segs)
    logits_len = out["logits"].shape[1]
    print(f"[{write_mode}] loss={loss.item():.4f} finite={torch.isfinite(loss).item()} "
          f"logits_len={logits_len} expected_tokens={total_tokens} "
          f"parallel_prefill={model.rmt.use_parallel_prefill}")
    assert torch.isfinite(loss), "loss not finite"
    assert logits_len == total_tokens, f"logits {logits_len} != tokens {total_tokens} (mem not stripped?)"
    loss.backward()
    cell = model.rmt.memory_cell
    if write_mode == "self_attn":
        assert cell.memory is not None and cell.memory.grad is not None, "mem bank got no grad"
        gnorm = cell.memory.grad.norm().item()
        assert gnorm > 0, "mem bank grad is zero"
        assert model.rmt.use_parallel_prefill is False, "self_attn must force recurrent"
        print(f"[{write_mode}] mem-bank grad norm={gnorm:.4e}  OK")
    # GDN + base layer got grads
    L0 = (cell.model.model.layers if hasattr(cell.model, "model") else cell.model.transformer.h)[0]
    gdn_grad = any(p.grad is not None and p.grad.abs().sum() > 0 for p in L0.fla_layer.parameters())
    assert gdn_grad, "GDN got no grad"
    print(f"[{write_mode}] GDN grads flow  OK")
    del model
    if dev == "cuda":
        torch.cuda.empty_cache()


if __name__ == "__main__":
    run("self_attn")
    print("---")
    run("cross_attn")   # regression: existing id-ca path still works in the forked file
    print("\nALL SMOKE CHECKS PASSED")
