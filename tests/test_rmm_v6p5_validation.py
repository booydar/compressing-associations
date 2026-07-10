"""v6p5 validation for the cross_attn_tf (full-transformer cross-attention) modes.

Checks:
  (1) parallel-prefill == recurrent logits for the new modes, on BOTH a gpt2 backbone
      (learned abs positions, no RoPE) and a llama backbone (RoPE), threading ON/OFF.
  (2) the memory block is a REAL backbone decoder layer (same class as the backbone,
      and it has an MLP) -- "full transformer power", not the bare LlamaCrossAttention.
  (3) cross_attn_tf differs from plain cross_attn (the MLP/residuals change the output).
Run with the fla python on a CUDA box.
"""
import os, sys, copy, torch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from transformers import GPT2Config, LlamaConfig
from modeling_rmt.huggingface_rmm_v6p5 import RecurrentMemoryBase as RMM, RecurrentMemoryConfig as Cfg

H, NH, HD, NL, VOCAB, B = 64, 1, 32, 2, 100, 2
DEV = "cuda"; ATOL = 1e-3


def gpt2_cfg():
    return GPT2Config(vocab_size=VOCAB, n_embd=H, n_layer=NL, n_head=NH,
                      n_positions=512, torch_dtype="float32")


def llama_cfg():
    return LlamaConfig(vocab_size=VOCAB, hidden_size=H, intermediate_size=4 * H,
                       num_hidden_layers=NL, num_attention_heads=NH,
                       num_key_value_heads=NH, head_dim=H // NH,
                       max_position_embeddings=512, torch_dtype="float32")


def build(base_cfg, write_mode, read_mode, M=8, thread_memory=True):
    torch.manual_seed(0); torch.cuda.manual_seed_all(0)
    cfg = Cfg(base_model_config=base_cfg, fla_layer_name="GatedDeltaNet",
              num_heads=NH, head_dim=HD, expand_v=2.0, conv_size=4,
              write_mode=write_mode, read_mode=read_mode, num_memory_vectors=M,
              write_value_dim=None, num_memory_heads=1,
              use_parallel_prefill=True, max_n_segments=10, thread_memory=thread_memory)
    return RMM(cfg).to(DEV).eval()


def segs(n_seg, seg_len):
    g = torch.Generator().manual_seed(0); out = []
    for _ in range(n_seg):
        ids = torch.randint(0, VOCAB, (B, seg_len), generator=g)
        out.append({"input_ids": ids.to(DEV),
                    "attention_mask": torch.ones(B, seg_len, dtype=torch.long, device=DEV),
                    "labels": torch.full((B, seg_len), -100, dtype=torch.long, device=DEV),
                    "labels_mask": torch.zeros(B, seg_len, dtype=torch.bool, device=DEV)})
    return out


def logits(m, S, T):
    sg = segs(S + 1, T); lab = torch.cat([s["labels"] for s in sg], dim=1)
    m.set_parallel_prefill(True)
    with torch.no_grad(): p = m(segments=copy.deepcopy(sg), labels=lab).logits
    m.set_parallel_prefill(False)
    with torch.no_grad(): r = m(segments=copy.deepcopy(sg), labels=lab).logits
    return p, r


def cell_of(m):
    return [mm for mm in m.modules() if mm.__class__.__name__ == "RecurrentMemoryCell"][0]


def layers_of(cell):
    return cell.model.model.layers if hasattr(cell.model, "model") else cell.model.transformer.h


print("=" * 64, "\n(1) parallel == recurrent for cross_attn_tf, gpt2 + llama, thread ON/OFF")
fail = 0
for arch, mk in [("gpt2", gpt2_cfg), ("llama", llama_cfg)]:
    for (wm, rm) in [("cross_attn_tf", "cross_attn_tf"),
                     ("cross_attn_tf", "identity")]:
        for tm in [True, False]:
            m = build(mk(), wm, rm, M=8, thread_memory=tm)
            p, r = logits(m, S=4, T=5)
            d = (p - r).abs().max().item()
            ok = "OK " if d < ATOL else "FAIL"
            if d >= ATOL: fail += 1
            print(f"  {ok} {arch:5s} write={wm:13s} read={rm:13s} thread={tm!s:5s}  max|p-r|={d:.2e}")
            del m

print("=" * 64, "\n(2) memory block IS a full backbone decoder layer (same class + has MLP)")
for arch, mk in [("gpt2", gpt2_cfg), ("llama", llama_cfg)]:
    m = build(mk(), "cross_attn_tf", "cross_attn_tf", M=8)
    cell = cell_of(m)
    L0 = layers_of(cell)[0]
    base_cls = type(L0.base_layer).__name__
    cblk = L0.compress.block.layer
    dblk = L0.decompress.block.layer
    c_ok = type(cblk).__name__ == base_cls and type(dblk).__name__ == base_cls
    has_mlp = any("mlp" in n.lower() for n, _ in cblk.named_children())
    print(f"  {arch:5s} base_layer={base_cls}  compress.block={type(cblk).__name__}  "
          f"decompress.block={type(dblk).__name__}  same={c_ok}  has_mlp={has_mlp}")
    if not (c_ok and has_mlp): fail += 1
    del m

print("=" * 64, "\n(3) cross_attn_tf != plain cross_attn (MLP/residual change the output)")
for arch, mk in [("gpt2", gpt2_cfg), ("llama", llama_cfg)]:
    m_tf = build(mk(), "cross_attn_tf", "cross_attn_tf", M=8)
    m_ca = build(mk(), "cross_attn", "cross_attn", M=8)
    p_tf, _ = logits(m_tf, 4, 5); p_ca, _ = logits(m_ca, 4, 5)
    d = (p_tf - p_ca).abs().max().item()
    print(f"  {arch:5s} max|tf-ca|={d:.2e} -> {'differs' if d > 1e-4 else 'SUSPICIOUSLY-EQUAL'}")
    del m_tf, m_ca

print("=" * 64)
print("ALL OK" if fail == 0 else f"{fail} FAILURE(S)")
