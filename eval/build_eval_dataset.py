"""Build a Noisy-AR *eval-only* dataset with a fixed total noise budget.

Differs from build_noisy_kv_dataset.py:
  - Total number of noise blocks per sample is set directly via
    --total_noise_blocks (NB), independent of n_pairs. (Original builder ties
    it to n_pairs * K and only supports integer K.)
  - Only emits a `valid` split (plus a 1-sample stub `train` to keep the
    DatasetDict shape that the trainers expect).

Output (default):
  data/N{N}-K{K}V{V}-V62_NB{NB}-B{B}_eval{n_valid}
"""
import argparse
import os
import random
import string

import datasets as ds

BASE_KV_ALPHABET = string.ascii_letters + string.digits  # 62 chars
KV_PAIR_TEMPLATE = "!{k}:{v}!"
SEG_TERMINATOR = "|"


def make_sample(n_pairs, k_length, v_length, n_noise_blocks, noise_block_size,
                alphabet=BASE_KV_ALPHABET):
    keys, used = [], set()
    while len(keys) < n_pairs:
        k = "".join(random.choice(alphabet) for _ in range(k_length))
        if k not in used:
            used.add(k); keys.append(k)
    values = ["".join(random.choice(alphabet) for _ in range(v_length))
              for _ in range(n_pairs)]
    kv_dict = dict(zip(keys, values))

    kv_units = [KV_PAIR_TEMPLATE.format(k=k, v=v) for k, v in zip(keys, values)]
    noise_units = [
        "".join(random.choice(alphabet) for _ in range(noise_block_size))
        for _ in range(n_noise_blocks)
    ]
    units = kv_units + noise_units
    random.shuffle(units)
    context = "".join(units) + SEG_TERMINATOR

    k_for_query = random.choice(keys)
    query = f"?!{k_for_query}:"
    target = f"{kv_dict[k_for_query]}!|"
    return {"context": context, "query": query, "target": target}


def build(args):
    random.seed(args.seed)
    samples = [
        make_sample(
            n_pairs=args.n_pairs,
            k_length=args.n_keys,
            v_length=args.n_values,
            n_noise_blocks=args.total_noise_blocks,
            noise_block_size=args.noise_block_size,
        )
        for _ in range(args.n_valid)
    ]
    valid = ds.Dataset.from_dict({
        "context": [s["context"] for s in samples],
        "query":   [s["query"]   for s in samples],
        "target":  [s["target"]  for s in samples],
    })
    # Trainers in this repo always read DatasetDict({'train', 'valid'}).
    # Provide a 1-sample stub train so the dict shape matches; it is never used.
    train = ds.Dataset.from_dict({
        "context": [valid[0]["context"]],
        "query":   [valid[0]["query"]],
        "target":  [valid[0]["target"]],
    })
    dataset = ds.DatasetDict({"train": train, "valid": valid})

    if args.out_path:
        out = args.out_path
    else:
        out = (
            f"./data/N{args.n_pairs}-K{args.n_keys}V{args.n_values}"
            f"-V62_NB{args.total_noise_blocks}-B{args.noise_block_size}"
            f"_eval{args.n_valid}"
        )
    if os.path.exists(out) and not args.overwrite:
        print(f"skip (exists): {out}"); return
    dataset.save_to_disk(out)

    ex = valid[0]
    print(f"saved: {out}")
    print(f"  n_valid={len(valid)}  noise_blocks={args.total_noise_blocks}  "
          f"context_len={len(ex['context'])}")
    print(f"  context[:140]={ex['context'][:140]!r} ...")
    print(f"  query={ex['query']!r}  target={ex['target']!r}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n_pairs", type=int, required=True,
                   help="N: number of KV pairs per sample")
    p.add_argument("--total_noise_blocks", type=int, required=True,
                   help="NB: total noise blocks per sample (fixed, no vary).")
    p.add_argument("--noise_block_size", type=int, default=7,
                   help="B: chars per noise block (default 7 = KV-pair size).")
    p.add_argument("--n_keys", type=int, default=2)
    p.add_argument("--n_values", type=int, default=2)
    p.add_argument("--n_valid", type=int, default=2000)
    p.add_argument("--seed", type=int, default=142)
    p.add_argument("--out_path", type=str, default=None)
    p.add_argument("--overwrite", action="store_true")
    build(p.parse_args())
