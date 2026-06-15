"""Causal leak check (zero cache before QT), parameterized by checkpoint/module.

Usage:
    leak_test_general.py --module huggingface_rmm_v6p2 \
        --runner run_rmm_on_kv_retrieval-v6p2.py \
        --ckpt <checkpoint dir> --data data/N16-K2V2-V62_1M [--n 1024]

EM collapses to ~chance when the memory state is wiped before QT => genuine
retrieval, no bypass. EM stays high => leak.
"""
import os, sys, json, types, argparse, importlib.util
import torch
from torch.utils.data import DataLoader
import datasets
from transformers import AutoTokenizer, LlamaConfig

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
DEVICE = "cuda"

ap = argparse.ArgumentParser()
ap.add_argument("--module", required=True)
ap.add_argument("--runner", required=True)
ap.add_argument("--ckpt", required=True)
ap.add_argument("--data", required=True)
ap.add_argument("--tps", type=int, default=7)
ap.add_argument("--n", type=int, default=1024)
ap.add_argument("--bs", type=int, default=64)
args = ap.parse_args()

mod = importlib.import_module(f"modeling_rmt.{args.module}")
RecurrentMemoryBase = mod.RecurrentMemoryBase
RecurrentMemoryConfig = mod.RecurrentMemoryConfig
RecurrentMemoryCell = mod.RecurrentMemoryCell
Cache = mod.Cache


def load_collate(tokenizer):
    spec = importlib.util.spec_from_file_location("runner", os.path.join(ROOT, args.runner))
    r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
    r.tokenizer = tokenizer
    r.args = types.SimpleNamespace(memory_task_freq=0.0, memory_task=None,
                                   tokens_per_segment=args.tps, memory_key_size=2,
                                   memory_value_size=2)
    return r.collate_fn


def build_model():
    cfg = json.load(open(os.path.join(args.ckpt, "config.json")))
    base = LlamaConfig(**cfg["base_model_config"])
    keys = ["fla_layer_name","num_heads","head_dim","expand_v","conv_size","use_short_conv",
            "state_size","num_memory_vectors","write_mode","read_mode","write_value_dim",
            "num_memory_heads","use_parallel_prefill","max_n_segments","think_token_id",
            "answer_token_id","bos_token_id","eos_token_id"]
    kw = {k: cfg[k] for k in keys if k in cfg}
    if "gap_width" in cfg:
        kw["gap_width"] = cfg["gap_width"]
    rc = RecurrentMemoryConfig(base_model_config=base, **kw)
    model = RecurrentMemoryBase(rc).to(DEVICE).eval()
    from safetensors.torch import load_model
    load_model(model, os.path.join(args.ckpt, "model.safetensors"), strict=False, device=DEVICE)
    print(f"module={args.module}  gap_width(cfg)={cfg.get('gap_width','<none>')}  "
          f"write/read={cfg.get('write_mode')}/{cfg.get('read_mode')}  M={cfg.get('num_memory_vectors')}")
    return model


def em(model, dl, ignore, zero_pre_qt):
    orig = RecurrentMemoryCell.parallel_forward
    if zero_pre_qt:
        def patched(self, *a, **k):
            out = orig(self, *a, **k)
            for L in RecurrentMemoryCell._get_transformer_layers(self.model):
                L.cache = Cache()
            return out
        RecurrentMemoryCell.parallel_forward = patched
    correct = total = 0
    try:
        with torch.no_grad():
            for b in dl:
                segs = [{k: v.to(DEVICE) for k, v in s.items()} for s in b["segments"]]
                lbl = b["labels"].to(DEVICE)
                lg = model(segments=segs, labels=lbl)["logits"][:, :-1].argmax(-1)
                la = lbl[:, 1:]
                m = (la != -100)
                for t in ignore: m &= (la != t)
                for i in range(la.shape[0]):
                    if m[i].any():
                        total += 1
                        correct += bool((lg[i][m[i]] == la[i][m[i]]).all())
    finally:
        RecurrentMemoryCell.parallel_forward = orig
    return correct / max(total, 1), total


def main():
    tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "tokenizers/kv_alphabet_62"))
    collate = load_collate(tok)
    model = build_model()
    valid = datasets.load_from_disk(os.path.join(ROOT, args.data))["valid"].select(range(args.n))
    dl = DataLoader(valid, batch_size=args.bs, collate_fn=collate)
    ignore = set(tok.encode('!', add_special_tokens=False) + tok.encode('|', add_special_tokens=False))
    a, n = em(model, dl, ignore, False); print(f"\n[A] normal              EM = {a:.4f}  (n={n})")
    z, n = em(model, dl, ignore, True);  print(f"[B] cache zeroed pre-QT EM = {z:.4f}  (n={n})")
    print("\n--- verdict ---")
    if a > 0.5 and z < 0.05:
        print(f"EM {a:.3f} -> {z:.3f} when state wiped before QT. GENUINE retrieval, no bypass.")
    elif z >= 0.5:
        print(f"EM stays {z:.3f} with zero state — LEAK: answer reaches QT without memory.")
    else:
        print(f"Inconclusive: {a:.3f} -> {z:.3f}")


if __name__ == "__main__":
    main()
