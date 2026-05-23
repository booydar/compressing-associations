"""Build a Noisy-AR KV-retrieval dataset.

Two parameters:
  --noise_blocks_per_pair K     how many noise blocks per KV pair (required)
  --noise_block_size      B     chars per noise block (default 7 = KV-pair size)

Each sample has N KV pairs and N*K noise blocks of B chars each, randomly
interleaved. So with N=8, K=2, B=7: every sample has 8 pairs + 16 noise
blocks = 8*7 + 16*7 = 168 noise+KV chars + '|' = 169 chars.

With --vary_noise: the per-sample total noise block count is drawn uniformly
from [1, N*K]. So a sample has anywhere from 1 to N*K noise blocks.

Output:
  fixed:  data/N{N}-K2V2-V62_K{K}-B{B}_1M
  vary:   data/N{N}-K2V2-V62_K{K}-vary-B{B}_1M
"""
import argparse
import os
import random
import string
from collections import Counter

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
    n_total = args.n_train + args.n_valid
    max_blocks = args.n_pairs * args.noise_blocks_per_pair  # N*K

    def pick_n_blocks():
        if args.vary_noise:
            return random.randint(1, max_blocks)
        return max_blocks

    per_sample_blocks = [pick_n_blocks() for _ in range(n_total)]
    samples = [
        make_sample(
            n_pairs=args.n_pairs,
            k_length=args.n_keys,
            v_length=args.n_values,
            n_noise_blocks=n,
            noise_block_size=args.noise_block_size,
        )
        for n in per_sample_blocks
    ]

    # Show the actual distribution we produced.
    dist = Counter(per_sample_blocks)
    print(f"per-sample noise-block count (range: 1..{max_blocks}, "
          f"vary={args.vary_noise}):")
    for n_blocks, c in sorted(dist.items())[:12]:
        share = 100.0 * c / n_total
        print(f"  {n_blocks:>4} blocks  ({n_blocks * args.noise_block_size:>5} chars)  "
              f"count={c:>7}  ({share:5.1f}%)")
    if len(dist) > 12:
        print(f"  ... +{len(dist)-12} more buckets")

    raw = ds.Dataset.from_dict({
        "context": [s["context"] for s in samples],
        "query":   [s["query"]   for s in samples],
        "target":  [s["target"]  for s in samples],
    })
    split = raw.train_test_split(test_size=args.n_valid, seed=args.seed)
    dataset = ds.DatasetDict({"train": split["train"], "valid": split["test"]})

    if args.out_path:
        out = args.out_path
    else:
        size_tag = (f"{n_total // 1_000_000}M" if n_total >= 1_000_000
                    else f"{n_total // 1000}K")
        vary_tag = "-vary" if args.vary_noise else ""
        out = (
            f"./data/N{args.n_pairs}-K{args.n_keys}V{args.n_values}"
            f"-V62_K{args.noise_blocks_per_pair}{vary_tag}"
            f"-B{args.noise_block_size}_{size_tag}"
        )
    if os.path.exists(out) and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing dataset at {out}")
    dataset.save_to_disk(out)

    ex = dataset["train"][0]
    print(f"saved: {out}")
    print(f"n_train={len(dataset['train'])}  n_valid={len(dataset['valid'])}")
    print(f"example context (len={len(ex['context'])}): {ex['context'][:160]!r} ...")
    print(f"        query:  {ex['query']!r}")
    print(f"        target: {ex['target']!r}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n_pairs", type=int, required=True,
                   help="N: number of KV pairs per sample")
    p.add_argument("--noise_blocks_per_pair", type=int, required=True,
                   help="K: noise blocks per KV pair. Total noise blocks per "
                        "sample = N*K (or uniform 1..N*K with --vary_noise).")
    p.add_argument("--noise_block_size", type=int, default=7,
                   help="B: chars per noise block (default 7 = KV-pair size, "
                        "for clean tokens_per_segment=7 alignment).")
    p.add_argument("--vary_noise", action="store_true",
                   help="per-sample number of noise blocks drawn uniformly "
                        "from [1, N*K] instead of fixed N*K.")
    p.add_argument("--n_keys", type=int, default=2)
    p.add_argument("--n_values", type=int, default=2)
    p.add_argument("--n_train", type=int, default=1_000_000)
    p.add_argument("--n_valid", type=int, default=5_000)
    p.add_argument("--seed", type=int, default=142)
    p.add_argument("--out_path", type=str, default=None)
    p.add_argument("--overwrite", action="store_true")
    build(p.parse_args())
