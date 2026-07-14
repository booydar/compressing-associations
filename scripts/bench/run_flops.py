"""FLOP counter companion to run_efficiency.py (paper Table E5 -> Pareto plot).

Reuses the exact model builders + forward payloads from run_efficiency.py and
measures forward-pass FLOPs per sequence with torch.utils.flop_counter.FlopCounterMode.

Methodology note (important, printed in the CSV header comment too):
  - FlopCounterMode counts aten ops routed through the dispatcher. This INCLUDES
    all linear projections, FFNs, and scaled_dot_product_attention (so the O(T^2)
    self-attention / intra-segment attention cost IS counted).
  - It does NOT count FLA's fused Triton chunk-recurrence kernels (the linear GDN
    core), which bypass the aten dispatcher. That core is O(T * state) -- linear in
    sequence length -- and is small relative to the projections at this scale. It is
    excluded identically for gdn / armt / rmm, so cross-variant comparison is fair;
    absolute FLOPs for SSM variants are a mild lower bound.

Measures FLOPs at batch_size=1 => value is FLOPs / sequence (matches the table's
per-seq wall-clock and lets you multiply by batch trivially).

Usage (remote A100, fla env):
    ~/envs/fla/bin/python scripts/bench/run_flops.py \
        --output runs-bench/flops.csv \
        --variants selfattn-1seg,gdn,armt,rmm-parallel,rmm-recurrent \
        --seq_len_pairs 32,128,256 \
        --tokens_per_seg 1,7,28
"""
from __future__ import annotations

import argparse
import csv
import gc
from pathlib import Path

import torch
from torch.utils.flop_counter import FlopCounterMode

# reuse everything from the timing benchmark
import run_efficiency as re

SEGMENT_VARIANTS = {"armt", "rmm-parallel", "rmm-recurrent"}


def build_payload(variant: str, tps: int, seq_tokens: int, cfg: "re.BenchCfg", bs: int = 1):
    if variant in SEGMENT_VARIANTS:
        return re.make_segments(bs, seq_tokens, tps if tps > 0 else 7,
                                cfg.vocab_size, cfg.device)
    return re.make_inputs(bs, seq_tokens, cfg.vocab_size, cfg.device)


def count_flops(model, payload, variant: str) -> int:
    counter = FlopCounterMode(display=False)
    with torch.no_grad():
        with counter:
            re._model_forward(model, payload, variant)
    return int(counter.get_total_flops())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=str, required=True)
    p.add_argument("--variants", type=str,
                   default="selfattn-1seg,gdn,armt,rmm-parallel,rmm-recurrent")
    p.add_argument("--seq_len_pairs", type=str, default="32,128,256")
    p.add_argument("--tokens_per_seg", type=str, default="1,7,28")
    p.add_argument("--tokens_per_pair", type=int, default=7)
    p.add_argument("--rmm_layers", type=int, default=4)
    p.add_argument("--rmm_M", type=int, default=4)
    p.add_argument("--intermediate_mult", type=int, default=4)
    p.add_argument("--armt_n_mem_tokens", type=int, default=1)
    p.add_argument("--armt_d_mem", type=int, default=32)
    p.add_argument("--state_size", type=int, default=32)
    args = p.parse_args()

    variants = args.variants.split(",")
    seq_pairs = [int(x) for x in args.seq_len_pairs.split(",")]
    tps_list = [int(x) for x in args.tokens_per_seg.split(",")]

    cfg = re.BenchCfg(
        L_rmm=args.rmm_layers,
        state_size=args.state_size,
        num_memory_vectors=args.rmm_M,
        intermediate_mult=args.intermediate_mult,
        armt_n_mem_tokens=args.armt_n_mem_tokens,
        armt_d_mem=args.armt_d_mem,
    )

    rows = []
    for variant in variants:
        # non-segment variants have a single "tps" slot (0)
        variant_tps = tps_list if variant in SEGMENT_VARIANTS else [0]
        for tps in variant_tps:
            for N in seq_pairs:
                seq_tokens = N * args.tokens_per_pair
                try:
                    model = re.build(variant, tps, cfg).to(cfg.device, dtype=cfg.dtype)
                    model.eval()
                    payload = build_payload(variant, tps, seq_tokens, cfg, bs=1)
                    flops = count_flops(model, payload, variant)
                    params_M = re.param_count_M(model)
                    gflops = flops / 1e9
                    print(f"{variant:16s} tps={tps:<3d} N={N:<4d} "
                          f"T={seq_tokens:<5d}  {gflops:12.4f} GFLOPs/seq  "
                          f"params={params_M:.3f}M")
                    rows.append({
                        "variant": variant,
                        "tokens_per_seg": tps,
                        "seq_pairs": N,
                        "seq_tokens": seq_tokens,
                        "batch_size": 1,
                        "phase": "prefill",
                        "flops_per_seq": flops,
                        "gflops_per_seq": round(gflops, 6),
                        "params_M": round(params_M, 4),
                        "dtype": "bf16",
                    })
                except Exception as e:  # noqa: BLE001
                    print(f"[error] {variant} tps={tps} N={N}: {e}")
                finally:
                    if "model" in dir():
                        del model
                    gc.collect()
                    torch.cuda.empty_cache()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
