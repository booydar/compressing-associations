"""v6p6 validation: identity is no longer a mode -- one disentangled path, and
"token-level/identity" is just M == T (mem size == segment size) via a sliced
over-capacity query bank.

Checks:
  (1) parallel-prefill == recurrent logits, for MECHANISMS {pool/unpool,
      cross_attn/cross_attn}, at BOTH identity (active=None -> M_eff=T) and
      compressed (active=4 < T), on gpt2 + llama, threading ON/OFF.
  (2) capacity/slice sanity: active=None -> M_eff == T; active=k -> M_eff == k;
      the same weights (capacity bank) serve both (one checkpoint, both modes).
  (3) causality / no future->past leak: perturbing input token at flattened
      position P leaves all logits at positions < P bit-unchanged (and changes
      something at >= P). Guards the read-only valve + ordering.
Run with the fla python on a CUDA box.
"""
import os, sys, copy, torch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from transformers import GPT2Config, LlamaConfig
from modeling_rmt.huggingface_rmm_v6p6 import RecurrentMemoryBase as RMM, RecurrentMemoryConfig as Cfg

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


def build(base_cfg, write_mode, read_mode, cap=32, active=None, thread_memory=True):
    torch.manual_seed(0); torch.cuda.manual_seed_all(0)
    cfg = Cfg(base_model_config=base_cfg, fla_layer_name="GatedDeltaNet",
              num_heads=NH, head_dim=HD, expand_v=2.0, conv_size=4,
              write_mode=write_mode, read_mode=read_mode,
              max_memory_vectors=cap, num_memory_vectors=active,
              write_value_dim=None, num_memory_heads=1,
              use_parallel_prefill=True, max_n_segments=10, thread_memory=thread_memory)
    return RMM(cfg).to(DEV).eval()


def segs(n_seg, seg_len, seed=0):
    g = torch.Generator().manual_seed(seed); out = []
    for _ in range(n_seg):
        ids = torch.randint(0, VOCAB, (B, seg_len), generator=g)
        out.append({"input_ids": ids.to(DEV),
                    "attention_mask": torch.ones(B, seg_len, dtype=torch.long, device=DEV),
                    "labels": torch.full((B, seg_len), -100, dtype=torch.long, device=DEV),
                    "labels_mask": torch.zeros(B, seg_len, dtype=torch.bool, device=DEV)})
    return out


def run(m, sg, parallel):
    lab = torch.cat([s["labels"] for s in sg], dim=1)
    m.set_parallel_prefill(parallel)
    with torch.no_grad():
        return m(segments=copy.deepcopy(sg), labels=lab).logits


def cell_of(m):
    return [mm for mm in m.modules() if mm.__class__.__name__ == "RecurrentMemoryCell"][0]


def layers_of(cell):
    return cell.model.model.layers if hasattr(cell.model, "model") else cell.model.transformer.h


MODES = [("pool", "unpool"), ("cross_attn", "cross_attn")]
fail = 0

print("=" * 70)
print("(1) parallel == recurrent  [pool/unpool, cross_attn]  x  {identity, c4}")
for arch, mk in [("gpt2", gpt2_cfg), ("llama", llama_cfg)]:
    for (wm, rm) in MODES:
        for active, tag in [(None, "identity(M=T)"), (4, "compress(M=4)")]:
            for tm in [True, False]:
                m = build(mk(), wm, rm, cap=32, active=active, thread_memory=tm)
                p = run(m, segs(4, 7), True)
                r = run(m, segs(4, 7), False)
                d = (p - r).abs().max().item()
                ok = "OK " if d < ATOL else "FAIL"
                if d >= ATOL: fail += 1
                print(f"  {ok} {arch:5s} {wm:11s}/{rm:11s} {tag:14s} thread={str(tm):5s}  maxdiff={d:.2e}")

print("=" * 70)
print("(2) capacity/slice: active=None -> M_eff=T ; active=k -> M_eff=k (one bank)")
m = build(llama_cfg(), "pool", "unpool", cap=32, active=None)
lyr = layers_of(cell_of(m))[0]
for T in (7, 12, 40):
    got = lyr._active_M(T)
    exp = min(T, 32)                      # identity, capped at capacity
    ok = "OK " if got == exp else "FAIL"; fail += (got != exp)
    print(f"  {ok} identity T={T:2d} -> M_eff={got} (exp {exp})")
m2 = build(llama_cfg(), "pool", "unpool", cap=32, active=4)
lyr2 = layers_of(cell_of(m2))[0]
for T in (7, 12):
    got = lyr2._active_M(T); exp = min(4, T)
    ok = "OK " if got == exp else "FAIL"; fail += (got != exp)
    print(f"  {ok} compress T={T:2d} -> M_eff={got} (exp {exp})")
# same-shape bank => one checkpoint can serve both:
assert lyr.read_queries.shape == lyr2.read_queries.shape == (32, H), "bank capacity must be identical"
print(f"  OK  bank capacity identical across modes: {tuple(lyr.read_queries.shape)}")

print("=" * 70)
print("(3) causality / no future->past leak (perturb token @P -> logits[:, :P] unchanged)")
for arch, mk in [("gpt2", gpt2_cfg), ("llama", llama_cfg)]:
    for (wm, rm) in MODES:
        for active, tag in [(None, "identity"), (4, "compress")]:
            m = build(mk(), wm, rm, cap=32, active=active, thread_memory=True)
            S, T = 4, 7
            base = segs(S + 1, T, seed=1)
            L0 = run(m, base, parallel=False)          # (B, (S+1)*T, V)
            P = 2 * T + 3                              # a position inside segment 2
            seg_i, off = P // T, P % T
            pert = copy.deepcopy(base)
            ids = pert[seg_i]["input_ids"].clone()
            ids[:, off] = (ids[:, off] + 1) % VOCAB
            pert[seg_i]["input_ids"] = ids
            L1 = run(m, pert, parallel=False)
            past = (L0[:, :P] - L1[:, :P]).abs().max().item()
            future = (L0[:, P:] - L1[:, P:]).abs().max().item()
            leak_ok = past < ATOL
            resp_ok = future > ATOL
            ok = "OK " if (leak_ok and resp_ok) else "FAIL"
            if not (leak_ok and resp_ok): fail += 1
            print(f"  {ok} {arch:5s} {wm:11s} {tag:9s}  past_leak={past:.2e} (<{ATOL})  future_resp={future:.2e} (>{ATOL})")

print("=" * 70)
print("(4) identity_init: at init (copy_gate=0) the write is a pure per-token copy")
for (wm, rm) in MODES:
    m = build(llama_cfg(), wm, rm, cap=32, active=None)      # identity, identity_init default True
    comp = layers_of(cell_of(m))[0].compress
    assert hasattr(comp, "copy_gate"), "identity_init must add copy_gate"
    g0 = comp.copy_gate.detach().abs().max().item()
    T = 7
    Hs = torch.randn(B, T, H, device=DEV)
    with torch.no_grad():
        w = comp(Hs, n_active=T)                              # M_eff = T
    d = (w - Hs).abs().max().item()                          # write == tokens?
    ok = "OK " if (g0 == 0.0 and d < 1e-5) else "FAIL"
    if not (g0 == 0.0 and d < 1e-5): fail += 1
    print(f"  {ok} {wm:11s} copy_gate={g0:.1e}  max|write - tokens|={d:.2e} (M=T copy)")

print("=" * 70)
print("ALL PASS" if fail == 0 else f"{fail} FAILURE(S)")
sys.exit(1 if fail else 0)
