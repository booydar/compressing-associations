#!/usr/bin/env python3
"""Collect the N32 token-level seed population and warm-start results.

Reports, per config: every seed's EM, the step at which it escaped the plateau,
and the COLLAPSE FREQUENCY (k/n) -- which is the quantity the paper should report
rather than a 2-seed mean. Escape step is read from the checkpoint trainer_state
log_history, so a run still in flight is included with whatever it has so far.

Usage (from repo root):
    python3 scripts/assoc-comp-rmm-rebuttal/collect_N32_results.py
"""
import glob
import json
import os
import statistics
import sys

# A run counts as escaped once eval EM clears this. The plateau sits at ~0.035
# (chance for 2-char values) and converged runs reach 0.86-0.99, so anything in
# between separates the two modes cleanly; nothing has ever been observed there.
ESCAPE_EM = 0.20

FAMILIES = [
    ("RMM v5p7 identity N32 tps7 (from scratch)",
     "runs-rebuttal/rmmv5p7/N32-K2V2-V62_1M/*identity_identity_lr*_pps1_tps7"),
    ("RMM v5p7 identity N32 tps224 (from scratch)",
     "runs-rmmv5p7/N32-K2V2-V62_1M/*identity_identity_lr*_pps32_tps224"),
    ("RMM v5p7 identity N32 tps7 (WARM-START from N16)",
     "runs-rmmv5p7-warmstart/N32-K2V2-V62_1M/*"),
    ("GDN baseline N32 ss32 ck4",
     "runs-rebuttal-default-sv/N32-K2V2-V62_1M/gated_delta_net_L4D128_ss32_ck4_*"),
]


def latest_trainer_state(run_dir):
    """Newest checkpoint's trainer_state.json, or None.

    Sorts by the numeric step, not lexicographically -- checkpoint-99000 must not
    beat checkpoint-143500.
    """
    cks = glob.glob(os.path.join(run_dir, "checkpoint-*"))
    if not cks:
        return None
    def step_of(p):
        try:
            return int(p.rsplit("-", 1)[1])
        except ValueError:
            return -1
    ck = max(cks, key=step_of)
    path = os.path.join(ck, "trainer_state.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def read_run(run_dir):
    em, budget = None, None
    res = os.path.join(run_dir, "all_results.json")
    if os.path.exists(res):
        try:
            with open(res) as fh:
                em = json.load(fh).get("eval_exact_match")
        except (json.JSONDecodeError, OSError):
            pass

    cfg = os.path.join(run_dir, "config.json")
    if os.path.exists(cfg):
        try:
            with open(cfg) as fh:
                budget = json.load(fh).get("cli_args", {}).get("max_steps")
        except (json.JSONDecodeError, OSError):
            pass

    escape, last_step = None, None
    ts = latest_trainer_state(run_dir)
    if ts:
        last_step = ts.get("global_step")
        evals = [l for l in ts.get("log_history", []) if "eval_exact_match" in l]
        for l in evals:
            if l["eval_exact_match"] > ESCAPE_EM:
                escape = l["step"]
                break
        if em is None and evals:            # still running: use best seen so far
            em = max(l["eval_exact_match"] for l in evals)
    return em, escape, last_step, budget


def main():
    root = os.getcwd()
    if not os.path.isdir(os.path.join(root, "scripts")):
        sys.exit("run me from the repo root (the dir containing scripts/ and runs-*/)")

    for title, pattern in FAMILIES:
        print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
        cfg_dirs = sorted(glob.glob(pattern))
        if not cfg_dirs:
            print("  (no runs yet)")
            continue

        for cfg_dir in cfg_dirs:
            runs = sorted(glob.glob(os.path.join(cfg_dir, "run_*")))
            if not runs:
                continue
            rows, ems = [], []
            for r in runs:
                em, escape, last_step, budget = read_run(r)
                if em is None:
                    continue
                ems.append(em)
                rows.append((
                    os.path.basename(r),
                    142 + int(os.path.basename(r).split("_")[1]),
                    em, escape, last_step, budget,
                ))
            if not rows:
                continue

            n = len(ems)
            collapsed = sum(1 for e in ems if e <= ESCAPE_EM)
            healthy = [e for e in ems if e > ESCAPE_EM]
            print(f"\n  {os.path.basename(cfg_dir)}")
            for name, seed, em, escape, last_step, budget in rows:
                mark = "COLLAPSE" if em <= ESCAPE_EM else "ok      "
                esc = f"escape@{escape}" if escape else "escape@-     "
                print(f"    {name:<8} seed {seed}  EM {em:6.4f}  {mark}  "
                      f"{esc:<15} step {last_step}/{budget}")
            mean = statistics.mean(ems)
            std = statistics.stdev(ems) if n > 1 else 0.0
            print(f"    -> n={n}  collapse {collapsed}/{n}  "
                  f"mean {mean:.4f} +- {std:.4f}  best {max(ems):.4f}"
                  + (f"  mean-of-healthy {statistics.mean(healthy):.4f}" if healthy else ""))
    print()


if __name__ == "__main__":
    main()
