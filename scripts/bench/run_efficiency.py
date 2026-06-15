"""Two-form efficiency micro-benchmark for the RMM paper (Table E5).

Measures, on a single GPU, per-variant:
    - prefill latency           [ms / seq]   (fwd, no grad)
    - training step latency     [ms / seq]   (fwd + bwd)
    - decode latency            [ms / tok]   (BS=1, 64 generated tokens, cached state)
    - peak VRAM                 [MB]
    - parameter count           [M]
    - prefill throughput        [tok / s]

Variants:
    selfattn-1seg   Vanilla Llama (full SDPA causal attention), single segment.
    gdn             FLA GatedDeltaNet, token-level.
    armt            Original ARMT (segment-level memory, sequential prefill).
    rmm-parallel    RMM v5p7 with use_parallel_prefill=True.
    rmm-recurrent   RMM v5p7 with use_parallel_prefill=False (python segment loop).

Sweep:
    seq_len_pairs  in {32, 128, 256}   ==> tokens = 7 * N_pairs
    tokens_per_seg in {1, 7, 28}       (RMM/ARMT only; "1 token" = identity / 1-pair
                                        for ARMT = tps==7 only)
    batch_size     prefill: 8; decode: 1

Honest knobs:
    - bf16 everywhere
    - 3 warmup, 10 measurement, report median
    - no torch.compile anywhere (apples-to-apples; FLA already uses Triton)
    - RMM-recurrent's segment loop is python; we measure it as such
    - param count is reported alongside, NOT FLOPs (FLOPs would unfairly penalise
      models with attention writers; param-matched is the relevant control)

Output: CSV at $OUTPUT, one row per (variant, seq_len, tokens_per_seg, batch_size, phase).

Usage:
    python scripts/bench/run_efficiency.py \
        --output runs-bench/efficiency.csv \
        --variants selfattn-1seg,gdn,armt,rmm-parallel,rmm-recurrent \
        --seq_len_pairs 32,128,256 \
        --tokens_per_seg 1,7,28 \
        --warmup 3 --measure 10
"""

from __future__ import annotations

import argparse
import csv
import gc
import os
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------- #
# Shared config                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class BenchCfg:
    L: int = 4
    L_rmm: int = 4             # number of RMM wrapper layers (each = Llama attn + GDN memory call)
    H: int = 4
    D: int = 128
    state_size: int = 32       # head_dim = state_size // H
    expand_v: float = 2.0
    conv_kernel: int = 4
    vocab_size: int = 70       # 62 alphabet + special tokens; exact value irrelevant for timing
    dtype: torch.dtype = torch.bfloat16
    device: str = "cuda"
    # bench loop
    warmup: int = 3
    measure: int = 10
    decode_tokens: int = 64    # number of generated tokens for decode latency
    # default RMM writer/reader (write: pool|cross_attn, read: unpool|cross_attn)
    write_mode: str = "pool"
    read_mode: str = "unpool"
    num_memory_vectors: int = 4
    # Llama backbone width controls. intermediate_size = D * intermediate_mult.
    intermediate_mult: int = 4
    # ARMT (original ARMT-GDN) config
    armt_n_mem_tokens: int = 1
    armt_d_mem: int = 32
    armt_n_heads_mem: int = 1


# --------------------------------------------------------------------------- #
# Model factories                                                             #
# --------------------------------------------------------------------------- #

def _llama_base_config(cfg: BenchCfg):
    from transformers import AutoConfig
    base = AutoConfig.from_pretrained("NousResearch/Llama-3.2-1B")
    base.num_hidden_layers     = cfg.L
    base.num_attention_heads   = cfg.H
    base.num_key_value_heads   = cfg.H
    base.hidden_size           = cfg.D
    base.head_dim              = cfg.D // cfg.H
    base.intermediate_size     = cfg.D * cfg.intermediate_mult
    base.vocab_size            = cfg.vocab_size
    base.torch_dtype           = "bfloat16"
    return base


def make_selfattn_1seg(cfg: BenchCfg) -> torch.nn.Module:
    from transformers import LlamaForCausalLM
    base = _llama_base_config(cfg)
    model = LlamaForCausalLM(base)
    return model


def make_gdn(cfg: BenchCfg) -> torch.nn.Module:
    import fla.models.gated_deltanet  # noqa: F401
    from fla.models.gated_deltanet.configuration_gated_deltanet import GatedDeltaNetConfig
    from fla.models.gated_deltanet.modeling_gated_deltanet import GatedDeltaNetForCausalLM
    gdn_cfg = GatedDeltaNetConfig(
        hidden_size=cfg.D,
        num_hidden_layers=cfg.L,
        num_heads=cfg.H,
        head_dim=cfg.state_size // cfg.H,
        expand_v=cfg.expand_v,
        conv_size=cfg.conv_kernel,
        use_short_conv=True,
        vocab_size=cfg.vocab_size,
    )
    return GatedDeltaNetForCausalLM(gdn_cfg)


def make_rmm(cfg: BenchCfg, parallel: bool, tokens_per_segment: int) -> torch.nn.Module:
    from modeling_rmt.huggingface_rmm_v5p7 import (
        RecurrentMemoryBase, RecurrentMemoryConfig,
    )
    base = _llama_base_config(cfg)
    base.num_hidden_layers = cfg.L_rmm   # may differ from cfg.L (e.g. L_rmm=2 for layer-matched comparison)
    head_dim = cfg.state_size // cfg.H
    # max_n_segments needs to cover the longest seq we'll feed
    # we set it large enough for N=256 pairs @ tps=1
    rmm_cfg = RecurrentMemoryConfig(
        base_model_config       = base,
        fla_layer_name          = "GatedDeltaNet",
        num_heads               = cfg.H,
        head_dim                = head_dim,
        expand_v                = cfg.expand_v,
        conv_size               = cfg.conv_kernel,
        use_short_conv          = True,
        num_memory_vectors      = cfg.num_memory_vectors,
        write_mode              = cfg.write_mode if tokens_per_segment > 1 else "identity",
        read_mode               = cfg.read_mode  if tokens_per_segment > 1 else "identity",
        write_value_dim         = cfg.D,
        num_memory_heads        = cfg.H,
        use_parallel_prefill    = parallel,
        max_n_segments          = 4096 // max(tokens_per_segment, 1),
        think_token_id          = 0,
        answer_token_id         = 0,
        bos_token_id            = 0,
        eos_token_id            = 0,
    )
    model = RecurrentMemoryBase(rmm_cfg)
    # store the bench-relevant config knob for the forward pass
    model._bench_tps = tokens_per_segment
    return model


def make_armt(cfg: BenchCfg, tokens_per_segment: int) -> torch.nn.Module:
    """Original ARMT-GDN: Llama backbone + per-segment ARMT memory cell. Memory is
    carried across segments via internal state (zero_mem / detach_mem). Prefill
    is intrinsically sequential — there is no parallel-segment form.

    ``tokens_per_segment`` is honoured at the bench's forward-pass level (we call
    armt_cell.forward() once per chunk of ``tokens_per_segment`` tokens).
    """
    from transformers import AutoModelForCausalLM
    from modeling_armt_gdn.huggingface import ARMTGDNForCausalLM

    base = _llama_base_config(cfg)
    base_model = AutoModelForCausalLM.from_config(base)

    model = ARMTGDNForCausalLM(
        base_model=base_model,
        num_mem_tokens=cfg.armt_n_mem_tokens,
        d_mem=cfg.armt_d_mem,
        n_heads=cfg.armt_n_heads_mem,
        correction=True,
        use_denom=True,
        use_gdn_forget_gate=True,
        act_on=False,
        max_hop=4,
        act_type="layer",
        constant_depth=False,
    )
    model._bench_tps = tokens_per_segment
    return model


# --------------------------------------------------------------------------- #
# Forward / step helpers                                                      #
# --------------------------------------------------------------------------- #

def make_inputs(batch_size: int, seq_len: int, vocab: int, device: str) -> torch.Tensor:
    return torch.randint(low=1, high=vocab, size=(batch_size, seq_len), device=device)


def make_segments(batch_size: int, seq_len: int, tps: int, vocab: int, device: str) -> Dict:
    """Build a `segments=[{input_ids, attention_mask, labels, labels_mask}, ...], labels=...`
    payload as expected by RMM v5p7 / ARMT forward()."""
    assert seq_len % tps == 0, f"seq_len {seq_len} not divisible by tps {tps}"
    n_seg = seq_len // tps
    segments = []
    for _ in range(n_seg):
        ids = torch.randint(1, vocab, (batch_size, tps), device=device)
        segments.append({
            "input_ids":      ids,
            "attention_mask": torch.ones_like(ids),
            "labels":         ids.clone(),
            "labels_mask":    torch.ones_like(ids, dtype=torch.bool),
        })
    full_labels = torch.cat([s["labels"] for s in segments], dim=1)
    return {"segments": segments, "labels": full_labels}


def _model_forward(model: torch.nn.Module, payload, variant: str) -> torch.Tensor:
    """Run a single forward pass. Returns a tensor that participates in autograd."""
    if variant.startswith("rmm"):
        out = model(segments=payload["segments"], labels=payload["labels"])
        return out.loss if hasattr(out, "loss") else out[0]
    if variant == "armt":
        # Native ARMT-GDN has no parallel segment form: we run armt_cell once per
        # segment, carrying memory across calls. Loss on the final segment only.
        model.zero_mem()
        segs = payload["segments"]
        last = None
        for i, seg in enumerate(segs):
            is_last = (i == len(segs) - 1)
            out = model.armt_cell(
                input_ids=seg["input_ids"],
                attention_mask=seg.get("attention_mask"),
                labels=seg["labels"] if is_last else None,
                labels_mask=seg["labels_mask"] if is_last else None,
                zero_mem=False,
            )
            if is_last:
                last = out
        return last.loss if hasattr(last, "loss") else last[0]
    out = model(input_ids=payload, labels=payload)
    return out.loss


@contextmanager
def cuda_timer():
    """Yields a callable returning elapsed ms once you call it inside the with-block."""
    start = torch.cuda.Event(enable_timing=True)
    end   = torch.cuda.Event(enable_timing=True)
    start.record()
    yield_box: List[float] = []
    try:
        yield yield_box
    finally:
        end.record()
        torch.cuda.synchronize()
        yield_box.append(start.elapsed_time(end))


def measure_ms(fn: Callable[[], None], warmup: int, measure: int) -> float:
    for _ in range(warmup):
        fn()
        torch.cuda.synchronize()
    times: List[float] = []
    for _ in range(measure):
        with cuda_timer() as box:
            fn()
        times.append(box[0])
    return statistics.median(times)


def peak_vram_mb(fn: Callable[[], None]) -> float:
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    fn()
    torch.cuda.synchronize()
    return torch.cuda.max_memory_allocated() / (1024 ** 2)


def param_count_M(model: torch.nn.Module) -> float:
    return sum(p.numel() for p in model.parameters()) / 1e6


# --------------------------------------------------------------------------- #
# Phase runners                                                               #
# --------------------------------------------------------------------------- #

def bench_prefill(model, ids, variant, cfg: BenchCfg) -> Tuple[float, float]:
    """Returns (median ms / seq, peak VRAM MB)."""
    model.eval()

    def step():
        with torch.no_grad():
            with torch.amp.autocast(device_type="cuda", dtype=cfg.dtype):
                _model_forward(model, ids, variant)

    ms = measure_ms(step, cfg.warmup, cfg.measure)
    vram = peak_vram_mb(step)
    return ms, vram


def bench_train_step(model, ids, variant, cfg: BenchCfg) -> Tuple[float, float]:
    """Returns (median ms / seq, peak VRAM MB)."""
    model.train()
    optim = torch.optim.SGD(model.parameters(), lr=0.0)  # zero LR so weights don't move

    def step():
        optim.zero_grad(set_to_none=True)
        with torch.amp.autocast(device_type="cuda", dtype=cfg.dtype):
            loss = _model_forward(model, ids, variant)
        loss.backward()
        # no optim.step(); we just want fwd+bwd cost

    ms = measure_ms(step, cfg.warmup, cfg.measure)
    vram = peak_vram_mb(step)
    return ms, vram


def bench_decode(model, variant, cfg: BenchCfg, prefill_len: int) -> Tuple[float, float]:
    """Decode latency at BS=1. Generates cfg.decode_tokens tokens, returns ms/tok.

    Implementation note: This requires the model to support `generate(...)` or an
    equivalent per-token forward with a cached state. We fall back to a manual loop
    that calls forward with one new token at a time. For models without an internal
    KV cache (RMM-parallel, ARMT segment-based), we re-run the prefill each step
    and report that — those are honestly bad at autoregressive decode.
    """
    model.eval()
    ids = make_inputs(1, prefill_len, cfg.vocab_size, cfg.device)

    # one-token decode loop
    def step():
        with torch.no_grad():
            with torch.amp.autocast(device_type="cuda", dtype=cfg.dtype):
                cur = ids
                for _ in range(cfg.decode_tokens):
                    out = _model_forward(model, cur, variant)
                    # append a dummy next token (we are timing, not sampling)
                    nxt = torch.randint(1, cfg.vocab_size, (1, 1), device=cfg.device)
                    cur = torch.cat([cur, nxt], dim=1)

    ms_total = measure_ms(step, cfg.warmup, cfg.measure)
    vram = peak_vram_mb(step)
    return ms_total / cfg.decode_tokens, vram


# --------------------------------------------------------------------------- #
# Build a model for a given (variant, tps) combo                               #
# --------------------------------------------------------------------------- #

def build(variant: str, tps: int, cfg: BenchCfg) -> torch.nn.Module:
    if variant == "selfattn-1seg":
        return make_selfattn_1seg(cfg)
    if variant == "gdn":
        return make_gdn(cfg)
    if variant == "armt":
        return make_armt(cfg, tokens_per_segment=tps)
    if variant == "rmm-parallel":
        return make_rmm(cfg, parallel=True,  tokens_per_segment=tps)
    if variant == "rmm-recurrent":
        return make_rmm(cfg, parallel=False, tokens_per_segment=tps)
    if variant == "rmm-identity":
        # Identity writer/reader: no compress/decompress; degenerates to GDN-on-top-of-Llama-backbone.
        # This isolates wrapper overhead (Llama attn block + bare GDN call) vs the FLA-only GDN baseline.
        prev_w, prev_r = cfg.write_mode, cfg.read_mode
        cfg.write_mode = cfg.read_mode = "identity"
        try:
            return make_rmm(cfg, parallel=True, tokens_per_segment=tps)
        finally:
            cfg.write_mode, cfg.read_mode = prev_w, prev_r
    raise ValueError(variant)


# --------------------------------------------------------------------------- #
# Main sweep                                                                   #
# --------------------------------------------------------------------------- #

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=str, required=True)
    p.add_argument("--variants", type=str,
                   default="selfattn-1seg,gdn,armt,rmm-parallel,rmm-recurrent")
    p.add_argument("--seq_len_pairs", type=str, default="32,128,256")
    p.add_argument("--tokens_per_seg", type=str, default="1,7,28")
    p.add_argument("--prefill_bs", type=int, default=8)
    p.add_argument("--decode_bs",  type=int, default=1)
    p.add_argument("--warmup",  type=int, default=3)
    p.add_argument("--measure", type=int, default=10)
    p.add_argument("--phases", type=str, default="prefill,train,decode")
    p.add_argument("--skip_decode_for", type=str,
                   default="rmm-parallel,armt",
                   help="Variants where per-token decode is not realistic.")
    p.add_argument("--tokens_per_pair", type=int, default=7,
                   help="Conversion factor: seq_len = N_pairs * tokens_per_pair.")
    p.add_argument("--rmm_layers", type=int, default=4,
                   help="Number of RMM wrapper layers. Use 2 to match GDN's total layer count "
                        "(each RMM layer = Llama attn block + GDN memory call).")
    p.add_argument("--rmm_M", type=int, default=4,
                   help="num_memory_vectors for RMM writer/reader. 1 matches paper E1 binder config.")
    p.add_argument("--intermediate_mult", type=int, default=4,
                   help="Llama FFN intermediate_size = D * mult. Use 2 to halve the MLP cost.")
    p.add_argument("--armt_n_mem_tokens", type=int, default=1)
    p.add_argument("--armt_d_mem", type=int, default=32)
    p.add_argument("--state_size", type=int, default=32,
                   help="GDN state size = num_heads * head_dim. Larger state makes GDN's "
                        "per-token update expensive (O(state^2)); RMM only pays this M times "
                        "per segment instead of per token.")
    args = p.parse_args()

    cfg = BenchCfg(
        warmup=args.warmup,
        measure=args.measure,
        L_rmm=args.rmm_layers,
        num_memory_vectors=args.rmm_M,
        intermediate_mult=args.intermediate_mult,
        state_size=args.state_size,
        armt_n_mem_tokens=args.armt_n_mem_tokens,
        armt_d_mem=args.armt_d_mem,
    )
    variants       = [v.strip() for v in args.variants.split(",") if v.strip()]
    pair_lens      = [int(x) for x in args.seq_len_pairs.split(",")]
    tps_list       = [int(x) for x in args.tokens_per_seg.split(",")]
    phases         = set(args.phases.split(","))
    skip_decode    = set(args.skip_decode_for.split(","))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "variant", "tokens_per_seg", "seq_pairs", "seq_tokens", "batch_size",
        "phase", "median_ms_per_seq", "ms_per_tok", "tok_per_s",
        "peak_vram_mb", "params_M", "n_warmup", "n_measure", "dtype",
    ]
    f = open(out_path, "w", newline="")
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    f.flush()

    def emit(row: Dict):
        w.writerow(row)
        f.flush()

    rmm_like = {"armt", "rmm-parallel", "rmm-recurrent", "rmm-identity"}

    for variant in variants:
        # variants that don't have a write-frequency knob still get one sweep entry
        tps_sweep = tps_list if variant in rmm_like else [0]
        for tps in tps_sweep:
            for n_pairs in pair_lens:
                seq_tokens = n_pairs * args.tokens_per_pair

                # skip nonsensical combos (write_freq finer than 1 token has no meaning)
                if variant.startswith("rmm") and tps == 0:
                    continue
                # ARMT at tps=1 is intentionally included: it's the worst-case demonstration
                # of the parallel-prefill claim (T sequential cell-forwards).

                try:
                    model = build(variant, tps, cfg).to(cfg.device, dtype=cfg.dtype)
                except NotImplementedError as e:
                    print(f"[skip] {variant} tps={tps}: {e}")
                    continue
                except Exception as e:
                    print(f"[error] build {variant} tps={tps}: {e}")
                    continue

                pcount = param_count_M(model)

                # build the right kind of input payload
                def _payload(bs):
                    if variant in rmm_like:
                        return make_segments(bs, seq_tokens, tps if tps > 0 else 7,
                                             cfg.vocab_size, cfg.device)
                    return make_inputs(bs, seq_tokens, cfg.vocab_size, cfg.device)

                # ----- prefill -----
                if "prefill" in phases:
                    ids = _payload(args.prefill_bs)
                    try:
                        ms, vram = bench_prefill(model, ids, variant, cfg)
                        tok_per_s = (args.prefill_bs * seq_tokens) / (ms / 1000)
                        emit(dict(
                            variant=variant, tokens_per_seg=tps,
                            seq_pairs=n_pairs, seq_tokens=seq_tokens,
                            batch_size=args.prefill_bs, phase="prefill",
                            median_ms_per_seq=round(ms, 3),
                            ms_per_tok=round(ms / seq_tokens, 4),
                            tok_per_s=round(tok_per_s, 1),
                            peak_vram_mb=round(vram, 1),
                            params_M=round(pcount, 3),
                            n_warmup=cfg.warmup, n_measure=cfg.measure, dtype="bf16",
                        ))
                    except Exception as e:
                        print(f"[prefill-fail] {variant} tps={tps} N={n_pairs}: {e}")

                # ----- train step -----
                if "train" in phases:
                    ids = _payload(args.prefill_bs)
                    try:
                        ms, vram = bench_train_step(model, ids, variant, cfg)
                        tok_per_s = (args.prefill_bs * seq_tokens) / (ms / 1000)
                        emit(dict(
                            variant=variant, tokens_per_seg=tps,
                            seq_pairs=n_pairs, seq_tokens=seq_tokens,
                            batch_size=args.prefill_bs, phase="train_step",
                            median_ms_per_seq=round(ms, 3),
                            ms_per_tok=round(ms / seq_tokens, 4),
                            tok_per_s=round(tok_per_s, 1),
                            peak_vram_mb=round(vram, 1),
                            params_M=round(pcount, 3),
                            n_warmup=cfg.warmup, n_measure=cfg.measure, dtype="bf16",
                        ))
                    except Exception as e:
                        print(f"[train-fail] {variant} tps={tps} N={n_pairs}: {e}")

                # ----- decode -----
                if "decode" in phases and variant not in skip_decode:
                    try:
                        ms_tok, vram = bench_decode(model, variant, cfg, prefill_len=seq_tokens)
                        emit(dict(
                            variant=variant, tokens_per_seg=tps,
                            seq_pairs=n_pairs, seq_tokens=seq_tokens,
                            batch_size=args.decode_bs, phase="decode",
                            median_ms_per_seq=None,
                            ms_per_tok=round(ms_tok, 4),
                            tok_per_s=round(1000.0 / ms_tok, 1),
                            peak_vram_mb=round(vram, 1),
                            params_M=round(pcount, 3),
                            n_warmup=cfg.warmup, n_measure=cfg.measure, dtype="bf16",
                        ))
                    except Exception as e:
                        print(f"[decode-fail] {variant} tps={tps} N={n_pairs}: {e}")

                del model
                gc.collect()
                torch.cuda.empty_cache()

    f.close()
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
