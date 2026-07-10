"""v6p4 validation: (1) parallel<->recurrent equivalence holds with cross-layer
threading ON and OFF, (2) threading actually changes computation (not a no-op),
(3) write cross-attn is multi-head. Run with the fla python on a CUDA box."""
import os, sys, copy, torch
from transformers import AutoConfig
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from modeling_rmt.huggingface_rmm_v6p4 import RecurrentMemoryBase as RMM, RecurrentMemoryConfig as Cfg

H, NH, HD, NL, VOCAB, B = 64, 1, 32, 2, 100, 2
DEV = "cuda"; ATOL = 1e-3

def base_cfg():
    c = AutoConfig.from_pretrained("gpt2"); c.n_layer=NL; c.n_head=NH; c.n_embd=H
    c.vocab_size=VOCAB; c.torch_dtype="float32"; return c

def build(write_mode, read_mode, M=8, num_memory_heads=1, write_value_dim=None, thread_memory=True):
    torch.manual_seed(0); torch.cuda.manual_seed_all(0)
    cfg = Cfg(base_model_config=base_cfg(), fla_layer_name="GatedDeltaNet",
              num_heads=NH, head_dim=HD, expand_v=2.0, conv_size=4,
              write_mode=write_mode, read_mode=read_mode, num_memory_vectors=M,
              write_value_dim=write_value_dim, num_memory_heads=num_memory_heads,
              use_parallel_prefill=True, max_n_segments=10, thread_memory=thread_memory)
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

print("="*60, "\n(1) parallel == recurrent, threading ON and OFF")
for (wm, rm) in [("identity","identity"), ("pool","identity"), ("cross_attn","cross_attn"),
                 ("pool","unpool"), ("cross_attn","identity")]:
    for tm in [True, False]:
        m = build(wm, rm, M=8, num_memory_heads=2 if "cross_attn" in (wm,rm) else 1, thread_memory=tm)
        p, r = logits(m, S=4, T=5)
        d = (p-r).abs().max().item()
        ok = "OK " if d < ATOL else "FAIL"
        print(f"  {ok} write={wm:10s} read={rm:9s} thread={tm!s:5s}  max|p-r|={d:.2e}")
        del m

print("="*60, "\n(2) threading actually engages (thread ON vs OFF must differ)")
for (wm, rm) in [("pool","identity"), ("cross_attn","cross_attn")]:
    m_on  = build(wm, rm, M=8, thread_memory=True)
    m_off = build(wm, rm, M=8, thread_memory=False)   # same seed/init
    p_on,_  = logits(m_on, 4, 5); p_off,_ = logits(m_off, 4, 5)
    d = (p_on - p_off).abs().max().item()
    print(f"  write={wm:10s} read={rm:9s}  max|on-off|={d:.2e}  -> {'engaged' if d>1e-5 else 'NO-OP?!'}")
    del m_on, m_off

print("="*60, "\n(3) write cross-attn is multi-head")
m = build("cross_attn", "cross_attn", M=8, num_memory_heads=4)
cell = [mm for mm in m.modules() if mm.__class__.__name__=="RecurrentMemoryCell"][0]
L0 = (cell.model.model.layers if hasattr(cell.model,"model") else cell.model.transformer.h)[0]
attn = getattr(L0.compress, "attn", None)
print(f"  compress.attn = {attn.__class__.__name__ if attn else None}, "
      f"num_heads = {getattr(attn,'num_heads',None)} (requested 4)")
print("DONE")
