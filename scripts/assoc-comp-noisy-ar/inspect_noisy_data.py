"""Visual inspector for Noisy-AR datasets.

Reads a built dataset from disk, mirrors the training-time collate+segment
logic from run_rmm_on_kv_retrieval-v5p4.py, and prints a colorized view
of the segmented input so you can visually verify:
  * where KV pairs sit
  * where noise blocks sit
  * whether noise blocks straddle segment boundaries
  * where the query/target sit, and the labels mask

Usage:
    python inspect_noisy_data.py ./data/N4-K2V2-V62_D32_1M --tokens_per_segment 39
    python inspect_noisy_data.py ./data/N8-K2V2-V62_D128_B7_1M -t 7 -n 3
"""
import argparse
import os
import re
import sys

from transformers import AutoTokenizer
import datasets as ds

# ANSI palette
RESET = "\x1b[0m"
COLORS = {
    "kv":      "\x1b[1;36m",   # cyan bold — KV pair characters
    "noise":   "\x1b[2;37m",   # dim white — random distractor chars
    "struct":  "\x1b[1;33m",   # yellow bold — !:|? structural chars
    "query":   "\x1b[1;35m",   # magenta bold — query tokens
    "target":  "\x1b[1;32m",   # green bold — target tokens (labels)
    "sepbar":  "\x1b[34m",     # blue — segment separators
    "header":  "\x1b[1;37m",   # white bold — section headers
}

STRUCT = set("!?:|")
KV_PAIR_REGEX = re.compile(r"!([A-Za-z0-9]{2,4}):([A-Za-z0-9]{2,4})!")


def classify_context_chars(context: str):
    """Return list of (char, kind) for the context string.

    kind ∈ {"kv", "noise", "struct"} — KV-pair chars include the '!K:V!'
    structural delimiters; "struct" is reserved for the trailing '|'.
    """
    n = len(context)
    kind = ["noise"] * n
    for m in KV_PAIR_REGEX.finditer(context):
        for i in range(m.start(), m.end()):
            kind[i] = "kv"
    for i, c in enumerate(context):
        if c == "|" or c == "?":
            kind[i] = "struct"
    return list(zip(context, kind))


def fmt_segment(chars_kinds, segment_offset, segment_size, default_color=None):
    """Pretty-print one segment's chars with per-char colour."""
    out = []
    for c, k in chars_kinds:
        color = COLORS.get(k, "") if default_color is None else default_color
        out.append(f"{color}{c}{RESET}")
    return "".join(out)


def inspect_sample(sample, tokenizer, tps, sample_idx):
    print(f"{COLORS['header']}── sample #{sample_idx} ──{RESET}")
    print(f"  context (len={len(sample['context'])}): {sample['context'][:100]!r}{'...' if len(sample['context']) > 100 else ''}")
    print(f"  query : {sample['query']!r}")
    print(f"  target: {sample['target']!r}")

    # Tokenise (char-level: each char → one token id).
    context_ids = tokenizer.encode(sample["context"], add_special_tokens=False)
    sep_id = tokenizer.encode("|", add_special_tokens=False)
    # Mirror v5p4 collate_fn: strip trailing '|' from context; prepend it to query.
    leading_sep = ""
    if sep_id and len(sep_id) == 1 and context_ids and context_ids[-1] == sep_id[0]:
        context_ids = context_ids[:-1]
        leading_sep = "|"
    query_ids = tokenizer.encode(sample["query"], add_special_tokens=False)
    target_ids = tokenizer.encode(sample["target"], add_special_tokens=False)
    qt_ids = (sep_id if leading_sep else []) + query_ids + target_ids

    # Per-char kind for the context (post-strip).
    stripped_context = sample["context"][:-1] if leading_sep else sample["context"]
    chars_kinds = classify_context_chars(stripped_context)
    assert len(chars_kinds) == len(context_ids), (
        f"char/id length mismatch: {len(chars_kinds)} vs {len(context_ids)} "
        f"— tokeniser may not be 1-char-per-token."
    )

    # Chunk into segments.
    n_segments = (len(context_ids) + tps - 1) // tps
    print(f"  tokens_per_segment={tps}  →  context segments = {n_segments}  (+1 QT segment)")
    bar = f"{COLORS['sepbar']}│{RESET}"
    legend = (
        f"  legend: {COLORS['kv']}KV{RESET}  {COLORS['noise']}noise{RESET}  "
        f"{COLORS['struct']}struct{RESET}  {COLORS['query']}query{RESET}  "
        f"{COLORS['target']}target{RESET}  {bar} segment-boundary"
    )
    print(legend)
    print()

    # Stitch segments together with visible boundaries.
    segment_view_parts = []
    for s in range(n_segments):
        seg_chars = chars_kinds[s * tps : (s + 1) * tps]
        segment_view_parts.append(fmt_segment(seg_chars, s * tps, tps))
        segment_view_parts.append(bar)
    print("  context segments (1 row, segment boundaries marked):")
    print("    " + "".join(segment_view_parts))

    # QT segment: query (magenta) + target (green).
    qt_str = (leading_sep + sample["query"] + sample["target"])
    qt_colored = []
    q_end = len(leading_sep) + len(sample["query"])
    for i, c in enumerate(qt_str):
        if i < q_end:
            qt_colored.append(f"{COLORS['query']}{c}{RESET}")
        else:
            qt_colored.append(f"{COLORS['target']}{c}{RESET}")
    print("  QT segment (last):")
    print("    " + "".join(qt_colored) + f"  {bar}")

    # Segment-content classification — the right metric for "do segments
    # cleanly contain either noise or KV content, but not both?"
    counts = {"noise-only": 0, "kv-only": 0, "mixed": 0, "short": 0}
    for s in range(n_segments):
        seg = chars_kinds[s * tps : (s + 1) * tps]
        if len(seg) < tps:
            counts["short"] += 1
            continue
        kinds_in_seg = {k for _, k in seg}
        has_noise = "noise" in kinds_in_seg
        has_kv = bool(kinds_in_seg & {"kv", "struct"})
        if has_noise and has_kv:
            counts["mixed"] += 1
        elif has_noise:
            counts["noise-only"] += 1
        else:
            counts["kv-only"] += 1
    print(
        f"  segment content: noise-only={counts['noise-only']}  "
        f"kv-only={counts['kv-only']}  mixed={counts['mixed']}  short={counts['short']}"
    )
    if counts["mixed"] == 0 and counts["short"] == 0:
        print(f"  {COLORS['target']}✓ every segment is purely noise or purely KV — clean alignment{RESET}")
    elif counts["mixed"] > 0:
        print(
            f"  {COLORS['struct']}⚠ {counts['mixed']} segment(s) mix noise + KV content. "
            f"For clean alignment use tokens_per_segment = noise_block_size "
            f"AND noise_block_size = KV-pair size (7 for K=V=2).{RESET}"
        )

    # Labels mask (target-only).
    print(f"  labels mask: {len(target_ids)} target token(s) at end of QT.")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data_path", help="path to a noisy KV dataset built by build_noisy_kv_dataset.py")
    p.add_argument("--tokenizer_path", default="./tokenizers/kv_alphabet_62/")
    p.add_argument("-t", "--tokens_per_segment", type=int, required=True,
                   help="segment size in tokens (== chars for this tokenizer)")
    p.add_argument("-n", "--num_samples", type=int, default=2)
    p.add_argument("--split", default="train", choices=["train", "valid"])
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    if not os.path.isdir(args.data_path):
        print(f"error: not a directory: {args.data_path}", file=sys.stderr)
        sys.exit(1)

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    dataset = ds.load_from_disk(args.data_path)
    split = dataset[args.split]

    print(f"{COLORS['header']}=== {args.data_path}  ({args.split}, {len(split)} samples) ==={RESET}")
    print(f"tokenizer: {args.tokenizer_path}  vocab={len(tokenizer)}")
    print(f"tokens_per_segment: {args.tokens_per_segment}")
    print()

    import random
    random.seed(args.seed)
    idxs = random.sample(range(len(split)), min(args.num_samples, len(split)))
    for i, idx in enumerate(idxs):
        inspect_sample(split[idx], tokenizer, args.tokens_per_segment, idx)


if __name__ == "__main__":
    main()
