"""Gold-standard correctness test: causal intervention on the context.

For a trained KV model, edit the CONTEXT and see if the prediction follows the
edit the way genuine key->value retrieval must:

  intact            : normal eval (control)              -> expect high EM
  corrupt-queried   : change the queried key's value in  -> expect high EM vs the
                      context to a new random value; the    NEW value (model reads
                      target becomes the new value           whatever the context
                                                             says -> genuine)
  corrupt-other     : change a NON-queried pair's value; -> expect high EM vs the
                      target stays the original value        ORIGINAL value (edit
                                                             is irrelevant -> no
                                                             spurious cross-talk)
  queried-old-value : corrupt-queried inputs, but score  -> expect ~0 (model must
                      against the OLD value                  NOT cling to the old
                                                             value = no memorization)

Usage: same flags as leak_test_general.py.
"""
import os, sys, json, types, argparse, importlib.util, random, string
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
ap.add_argument("--n", type=int, default=512)
ap.add_argument("--bs", type=int, default=64)
ap.add_argument("--vlen", type=int, default=2)
args = ap.parse_args()

mod = importlib.import_module(f"modeling_rmt.{args.module}")
RecurrentMemoryBase, RecurrentMemoryConfig = mod.RecurrentMemoryBase, mod.RecurrentMemoryConfig
ALPHABET = string.ascii_letters + string.digits


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
    rc = RecurrentMemoryConfig(base_model_config=base, **{k: cfg[k] for k in keys if k in cfg})
    model = RecurrentMemoryBase(rc).to(DEVICE).eval()
    from safetensors.torch import load_model
    load_model(model, os.path.join(args.ckpt, "model.safetensors"), strict=False, device=DEVICE)
    return model


def parse(sample):
    ctx, q, tgt = sample["context"], sample["query"], sample["target"]
    kj = q[2:].rstrip(":")                 # "?!KEY:" -> "KEY"
    vj = tgt.split("!")[0]                 # "VAL!|"  -> "VAL"
    return ctx, kj, vj


def new_value(old):
    while True:
        v = "".join(random.choice(ALPHABET) for _ in range(len(old)))
        if v != old:
            return v


def make_variants(sample):
    """Return dict of variant-name -> (modified_sample, scoring_target_value)."""
    ctx, kj, vj = parse(sample)
    pair = f"!{kj}:{vj}!"
    assert ctx.count(pair) == 1, f"queried pair not uniquely found: {pair!r} in {ctx!r}"
    out = {}
    # intact
    out["intact"] = (dict(sample), vj)
    # corrupt-queried: change queried value; score vs new value
    vj2 = new_value(vj)
    ctx_q = ctx.replace(pair, f"!{kj}:{vj2}!", 1)
    out["corrupt-queried"] = (
        {"context": ctx_q, "query": sample["query"], "target": f"{vj2}!|"}, vj2)
    # also score the corrupt-queried inputs against the OLD value (must fail)
    out["queried-old-value"] = (
        {"context": ctx_q, "query": sample["query"], "target": f"{vj}!|"}, vj)
    # corrupt-other: change a DIFFERENT pair's value; score vs original
    import re
    pairs = re.findall(r"!([0-9A-Za-z]{2}):([0-9A-Za-z]{2})!", ctx)
    others = [(k, v) for (k, v) in pairs if k != kj]
    if others:
        ok, ov = random.choice(others)
        ctx_o = ctx.replace(f"!{ok}:{ov}!", f"!{ok}:{new_value(ov)}!", 1)
        out["corrupt-other"] = (
            {"context": ctx_o, "query": sample["query"], "target": sample["target"]}, vj)
    return out


def em_for(model, samples, collate, ignore):
    dl = DataLoader(samples, batch_size=args.bs, collate_fn=collate)
    correct = total = 0
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
    return correct / max(total, 1), total


def main():
    random.seed(0)
    tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "tokenizers/kv_alphabet_62"))
    collate = load_collate(tok)
    model = build_model()
    ignore = set(tok.encode('!', add_special_tokens=False) + tok.encode('|', add_special_tokens=False))

    valid = datasets.load_from_disk(os.path.join(ROOT, args.data))["valid"].select(range(args.n))

    # sanity: show parse + corruption on 2 samples so format issues are visible
    for s in list(valid)[:2]:
        ctx, kj, vj = parse(s)
        v = make_variants(s)
        print(f"[dbg] key={kj!r} val={vj!r}")
        print(f"      ctx          : {ctx!r}")
        print(f"      corrupt-quer : {v['corrupt-queried'][0]['context']!r} target={v['corrupt-queried'][0]['target']!r}")
        print()

    buckets = {}
    for s in valid:
        for name, (mod_s, _tv) in make_variants(s).items():
            mod_s = dict(mod_s); mod_s["_score_target"] = _tv
            buckets.setdefault(name, []).append(mod_s)

    print(f"module={args.module}  n={args.n}\n")
    print(f"{'variant':>20} | {'EM':>7} | expectation")
    print("-" * 64)
    exp = {"intact": "high (control)",
           "corrupt-queried": "HIGH vs NEW value  => reads context faithfully",
           "corrupt-other": "HIGH vs ORIG       => no cross-talk",
           "queried-old-value": "~0                 => not memorizing old value"}
    for name in ("intact", "corrupt-queried", "corrupt-other", "queried-old-value"):
        if name not in buckets: continue
        e, n = em_for(model, buckets[name], collate, ignore)
        print(f"{name:>20} | {e:>6.3f} | {exp[name]}")

    print("\nVERDICT: correct iff corrupt-queried HIGH, corrupt-other HIGH, "
          "queried-old-value ~0. The model then provably reads the specific "
          "queried key's value from the (compressed) memory of the context.")


if __name__ == "__main__":
    main()
