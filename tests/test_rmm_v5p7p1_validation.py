"""v5p7.1 validation: parallel<->recurrent equivalence (threading ON/OFF),
threading engages, compress/decompress multi-head, GDN small-state honored."""
import os, sys, copy, torch
from transformers import AutoConfig
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from modeling_rmt.huggingface_rmm_v5p7p1 import RecurrentMemoryBase as RMM, RecurrentMemoryConfig as Cfg

H, NH, HD, NL, VOCAB, B = 64, 1, 32, 2, 100, 2
DEV = "cuda"; ATOL = 1e-3

def base_cfg():
    c = AutoConfig.from_pretrained("gpt2"); c.n_layer=NL; c.n_head=NH; c.n_embd=H
    c.vocab_size=VOCAB; c.torch_dtype="float32"; return c

def build(write_mode, read_mode, M=8, num_compress_heads=1, thread_memory=True):
    torch.manual_seed(0); torch.cuda.manual_seed_all(0)
    cfg = Cfg(base_model_config=base_cfg(), fla_layer_name="GatedDeltaNet",
              num_heads=NH, head_dim=HD, expand_v=2.0, conv_size=4,
              write_mode=write_mode, read_mode=read_mode, num_memory_vectors=M,
              num_compress_heads=num_compress_heads, use_parallel_prefill=True,
              max_n_segments=10, thread_memory=thread_memory)
    return RMM(cfg).to(DEV).eval()

def segs(n_seg, seg_len):
    g = torch.Generator().manual_seed(0); out=[]
    for _ in range(n_seg):
        ids = torch.randint(0, VOCAB, (B, seg_len), generator=g)
        out.append({"input_ids": ids.to(DEV),
                    "attention_mask": torch.ones(B, seg_len, dtype=torch.long, device=DEV),
                    "labels": torch.full((B, seg_len), -100, dtype=torch.long, device=DEV),
                    "labels_mask": torch.zeros(B, seg_len, dtype=torch.bool, device=DEV)})
    return out

def logits(m, S, T):
    sg = segs(S+1, T); lab = torch.cat([s["labels"] for s in sg], dim=1)
    m.set_parallel_prefill(True)
    with torch.no_grad(): p = m(segments=copy.deepcopy(sg), labels=lab).logits
    m.set_parallel_prefill(False)
    with torch.no_grad(): r = m(segments=copy.deepcopy(sg), labels=lab).logits
    return p, r

print("="*60, "\n(1) parallel == recurrent, threading ON and OFF (v5p7 native modes)")
for (wm, rm) in [("identity","identity"), ("pool","unpool"), ("cross_attn","cross_attn"),
                 ("cross_attn","unpool"), ("pool","cross_attn")]:
    for tm in [True, False]:
        ch = 2 if "cross_attn" in (wm, rm) else 1
        m = build(wm, rm, M=8, num_compress_heads=ch, thread_memory=tm)
        p, r = logits(m, S=4, T=5); d = (p-r).abs().max().item()
        print(f"  {'OK ' if d<ATOL else 'FAIL'} write={wm:10s} read={rm:9s} thread={tm!s:5s} max|p-r|={d:.2e}")
        del m

print("="*60, "\n(2) threading engages (ON vs OFF differ)")
for (wm, rm) in [("pool","unpool"), ("cross_attn","cross_attn")]:
    on = build(wm, rm, M=8, thread_memory=True); off = build(wm, rm, M=8, thread_memory=False)
    d = (logits(on,4,5)[0] - logits(off,4,5)[0]).abs().max().item()
    print(f"  write={wm:10s} read={rm:9s} max|on-off|={d:.2e} -> {'engaged' if d>1e-5 else 'NO-OP?!'}")
    del on, off

print("="*60, "\n(3) multi-head compress + GDN small state")
m = build("cross_attn", "cross_attn", M=8, num_compress_heads=4)
cell = [x for x in m.modules() if x.__class__.__name__=="RecurrentMemoryCell"][0]
L0 = (cell.model.transformer.h if hasattr(cell.model,"transformer") else cell.model.model.layers)[0]
print(f"  compress.attn heads = {L0.compress.attn.num_heads} (want 4)")
print(f"  decompress xattn heads = {L0.decompress.cross_attn.num_heads} (want 4)")
print(f"  GDN num_heads={L0.fla_layer.num_heads} head_k_dim={L0.fla_layer.head_k_dim} "
      f"state/layer={L0.fla_layer.num_heads*L0.fla_layer.head_k_dim*L0.fla_layer.head_v_dim} (small, not 786432)")
print("DONE")
