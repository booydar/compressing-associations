"""Collect noisy-AR eval metrics and build the comparison table.

Walks <runs_root>/**/eval_noisy/NB{nb}/metrics.json, parses each run path into
(model, base, write_frequency, M, lr, bs, seed, N_pairs), then aggregates
exact-match across seeds and pivots to a wide table indexed by
(model, write_frequency, M, lr) with columns NB{4,8,16,32,64,128}.

Usable as a script (prints + writes CSV) or imported from a notebook cell:

    from collect_noisy_eval import collect, pivot
    df = collect("runs-noisy-ar")
    print(pivot(df))
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

import pandas as pd


METRIC_KEYS = ("eval_exact_match", "exact_match", "eval_exact_match_base", "exact_match_base")
KNOWN_MODES = r"(unpool|pool|cross_attn|identity)"


def parse_run_name(name: str) -> dict:
    """Best-effort parse of training run-name into structured fields."""
    out: dict = {"run_name": name}

    if name.startswith("gdn_"):
        out["model"] = "GDN"
        out["write_frequency"] = "1 token"
    elif name.startswith("armt_"):
        out["model"] = "ARMT"
    elif name.startswith("rmmv5p4_") or name.startswith("rmmv5p"):
        out["model"] = "RMM"
    else:
        out["model"] = name.split("_", 1)[0].upper()

    # Common numeric fields encoded in the run name.
    m = re.search(r"_L(\d+)H(\d+)D(\d+)_", name)
    if m: out["L"], out["H"], out["D"] = map(int, m.groups())
    m = re.search(r"_ss(\d+)_", name)
    if m: out["state_size"] = int(m.group(1))
    m = re.search(r"_M(\d+)_", name)
    if m: out["M"] = int(m.group(1))
    m = re.search(r"_mem(\d+)d(\d+)_", name)
    if m:
        out["M"] = int(m.group(1))
        out["d_mem"] = int(m.group(2))
    m = re.search(r"_lr([0-9.eE+-]+)", name)
    if m: out["lr"] = float(m.group(1))
    m = re.search(r"_bs(\d+)", name)
    if m: out["bs"] = int(m.group(1))
    m = re.search(r"_pps(\d+)", name)
    if m: out["pps"] = int(m.group(1))
    m = re.search(r"_tps(\d+)", name)
    if m: out["tps"] = int(m.group(1))

    # Version / model family tag (for config_label).
    m = re.match(r"^(rmmv\d+(?:p\d*)?|armt|rmt|gated_delta_net|mamba2?|gdn)", name)
    if m:
        out["version"] = m.group(1)

    # write_value_dim (-md{N} or -wvd{N}).
    m = re.search(r"-(?:md|wvd)(\d+)", name)
    if m:
        out["write_value_dim_parsed"] = int(m.group(1))

    # Read/write mode from name (known modes: unpool, pool, cross_attn, identity).
    # Two-mode: _M{N}_{read}[H{n}]_{write}[-md/wvd{N}] followed by _ev/_ck/_lr/_bs.
    two = re.search(
        r"_M\d+_" + KNOWN_MODES + r"(?:H\d+)?_" + KNOWN_MODES
        + r"(?:-(?:md|wvd)\d+)?(?=_(?:ev|ck|lr|bs))",
        name,
    )
    if two:
        out["read_mode_parsed"] = two.group(1)
        out["write_mode_parsed"] = two.group(2)
    else:
        # Single-mode (rmmv3): _M{N}_{mode}_lr.
        one = re.search(r"_M\d+_" + KNOWN_MODES + r"_lr", name)
        if one:
            out["read_mode_parsed"] = one.group(1)
            out["write_mode_parsed"] = one.group(1)

    return out


def normalize_config_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Unify read/write mode columns and build convenience labels."""
    df = df.copy()

    if "write_value_dim" not in df.columns:
        df["write_value_dim"] = pd.NA
    if "write_value_dim_parsed" in df.columns:
        df["write_value_dim"] = df["write_value_dim"].fillna(df["write_value_dim_parsed"])

    for col in ("read_mode", "write_mode"):
        if col not in df.columns:
            df[col] = pd.NA
    if "read_mode_parsed" in df.columns:
        df["read_mode"] = df["read_mode"].fillna(df["read_mode_parsed"])
    if "write_mode_parsed" in df.columns:
        df["write_mode"] = df["write_mode"].fillna(df["write_mode_parsed"])

    # rmmv3 uses a single mode for both read and write.
    if "version" in df.columns:
        rmmv3_mask = (
            df["version"].astype(str).str.startswith("rmmv3", na=False)
            & df["read_mode"].isna()
            & df["write_mode"].notna()
        )
        df.loc[rmmv3_mask, "read_mode"] = df.loc[rmmv3_mask, "write_mode"]

    for col in ("read_mode", "write_mode"):
        df[col] = df[col].fillna("N/A")

    tag = df["version"] if "version" in df.columns else df.get("model", pd.Series("unknown", index=df.index))
    tag = tag.fillna(df.get("model")).astype(str)

    df["write_config"] = df["write_mode"].astype(str)
    mask_md = df["write_value_dim"].notna()
    df.loc[mask_md, "write_config"] = (
        df.loc[mask_md, "write_mode"].astype(str)
        + "-md"
        + df.loc[mask_md, "write_value_dim"].astype(int).astype(str)
    )

    df["config_label"] = (
        tag + "|"
        + df["read_mode"].astype(str)
        + "→"
        + df["write_config"].astype(str)
    )
    return df


def parse_dataset_name(name: str) -> dict:
    """Parse the training dataset folder name → {N_pairs, K_train_max}."""
    out: dict = {"train_dataset": name}
    m = re.search(r"^N(\d+)-", name)
    if m: out["N_pairs"] = int(m.group(1))
    m = re.search(r"_K(\d+)(-vary)?-B(\d+)_", name)
    if m:
        out["K_train"] = int(m.group(1))
        out["vary"] = bool(m.group(2))
        out["B"] = int(m.group(3))
    return out


def _pick_metric(d: dict) -> Optional[float]:
    for k in METRIC_KEYS:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def collect(runs_root: str | Path) -> pd.DataFrame:
    runs_root = Path(runs_root)
    rows = []
    for metrics_path in sorted(runs_root.glob("**/eval_noisy/NB*/metrics.json")):
        # …/<dataset>/<run_name>/run_<seed>/eval_noisy/NB{nb}/metrics.json
        try:
            nb = int(metrics_path.parent.name.removeprefix("NB"))
        except ValueError:
            continue
        run_seed_dir = metrics_path.parents[2]
        run_dir = run_seed_dir.parent
        dataset_dir = run_dir.parent

        seed_m = re.match(r"run_(\d+)$", run_seed_dir.name)
        seed = int(seed_m.group(1)) if seed_m else None

        try:
            with open(metrics_path) as f:
                metrics = json.load(f)
        except json.JSONDecodeError:
            continue
        em = _pick_metric(metrics)

        row = {
            "NB": nb,
            "seed": seed,
            "exact_match": em,
            "token_accuracy": metrics.get("eval_token_accuracy",
                                          metrics.get("token_accuracy")),
            "metrics_path": str(metrics_path),
            **parse_run_name(run_dir.name),
            **parse_dataset_name(dataset_dir.name),
        }
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return normalize_config_columns(df)


def derive_write_frequency(df: pd.DataFrame) -> pd.Series:
    """Map (model, tps, pps, N_pairs) → human-readable write-frequency label."""
    def _one(row):
        m = row.get("model")
        if m == "GDN":
            return "1 token"
        tps = row.get("tps")
        pps = row.get("pps")
        N = row.get("N_pairs")
        if tps == 1:
            return "1 token"
        if m == "ARMT":
            if tps == 7:
                return "1 pair"
            if tps and tps % 7 == 0:
                return f"{tps // 7} pairs"
        if m == "RMM":
            if pps == 1:
                return "1 pair"
            if pps and N and pps == N:
                return f"{N} pairs"
            if pps:
                return f"{pps} pairs"
        return None
    return df.apply(_one, axis=1)


def pivot(df: pd.DataFrame,
          index_cols=("model", "write_frequency", "M", "lr", "N_pairs"),
          value_col="exact_match",
          nb_order=(4, 8, 16, 32, 64, 128),
          agg="mean") -> pd.DataFrame:
    df = df.copy()
    if "write_frequency" not in df.columns:
        df["write_frequency"] = derive_write_frequency(df)
    index_cols = [c for c in index_cols if c in df.columns]
    grouped = (
        df.groupby(list(index_cols) + ["NB"], dropna=False)[value_col]
          .agg(agg)
          .reset_index()
    )
    wide = grouped.pivot(index=list(index_cols), columns="NB", values=value_col)
    # Reorder NB columns
    cols = [c for c in nb_order if c in wide.columns]
    wide = wide.reindex(columns=cols)
    wide.columns = [f"NB{c}" for c in wide.columns]
    return wide.sort_index()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs_root", default="runs-noisy-ar",
                   help="Root dir to scan (default: runs-noisy-ar)")
    p.add_argument("--out_csv_long", default=None,
                   help="Optional: write long-form (one row per (run, NB)) CSV")
    p.add_argument("--out_csv_wide", default=None,
                   help="Optional: write pivoted-table CSV")
    p.add_argument("--metric", default="exact_match",
                   choices=["exact_match", "token_accuracy"])
    args = p.parse_args()

    df = collect(args.runs_root)
    if df.empty:
        print(f"no metrics found under {args.runs_root}/**/eval_noisy/NB*/metrics.json")
        return
    df["write_frequency"] = derive_write_frequency(df)
    print(f"loaded {len(df)} (run, NB) rows from {df['run_name'].nunique()} runs")
    if args.out_csv_long:
        df.to_csv(args.out_csv_long, index=False)
        print(f"wrote long-form CSV → {args.out_csv_long}")

    wide = pivot(df, value_col=args.metric)
    print("\n=== mean across seeds ===")
    print(wide.round(4).to_string())
    if args.out_csv_wide:
        wide.to_csv(args.out_csv_wide)
        print(f"\nwrote wide CSV → {args.out_csv_wide}")


if __name__ == "__main__":
    main()
