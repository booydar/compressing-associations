#!/usr/bin/env python3
"""Read out the v6p6-unified grid without waiting for the big collector notebook.

Prints best EM, best token_accuracy, current step, and the recent slope of
token_accuracy for every run under the rebuttal roots plus the pre-existing
runs-rmmv6p6 tree.

WHY token_accuracy IS THE COLUMN TO WATCH
Across the whole grid EM ~= token_accuracy^2 -- the two value tokens fail
independently (50.94 vs 70.95^2 = 50.3; 44.60 vs 44.2; 90.70 vs 90.9; 99.02 vs
99.0). EM therefore squares away exactly the signal you need to call a cell early,
and a run at 71% tokacc is much closer to solving the task than its 51% EM looks.
The one place the identity breaks down is early/unstable runs where errors are
correlated (5.80 EM vs 41.07 tokacc), which is itself a useful tell.

`slope` is the change in token_accuracy (percentage points) over the last ~20k
steps. A cell that is still climbing has not converged and its number is a lower
bound -- the 200k budget produced three truncation artifacts in Table 2 already.

Usage:
    ./collect_v6p6.py                 # all roots
    ./collect_v6p6.py --root runs-rebuttal/rmmv6p6-unified
    ./collect_v6p6.py --sort em
"""
import argparse, glob, json, os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ROOTS = [
    "runs-rebuttal/rmmv6p6-unified",
    "runs-rebuttal/rmmv6p6ext",
    "runs-rebuttal/rmmv6p4-armt-seeds",
    "runs-rmmv6p6",
]


def state_path(d):
    p = os.path.join(d, "trainer_state.json")
    if os.path.exists(p):
        return p
    cks = sorted(glob.glob(os.path.join(d, "checkpoint-*/trainer_state.json")),
                 key=lambda x: int(x.split("checkpoint-")[1].split("/")[0]))
    return cks[-1] if cks else None


def summarise(d):
    sp = state_path(d)
    if not sp:
        return None
    s = json.load(open(sp))
    hist = [l for l in s.get("log_history", []) if "eval_exact_match" in l]
    if not hist:
        return None
    em = max(l["eval_exact_match"] for l in hist) * 100
    accs = [(l["step"], l.get("eval_token_accuracy")) for l in hist
            if l.get("eval_token_accuracy") is not None]
    acc = max(a for _, a in accs) * 100 if accs else float("nan")
    step = s.get("global_step", hist[-1]["step"])

    slope = float("nan")
    if len(accs) >= 2:
        last_step = accs[-1][0]
        window = [a for st, a in accs if st >= last_step - 20000]
        if len(window) >= 2:
            slope = (window[-1] - window[0]) * 100
    return dict(em=em, acc=acc, step=step, slope=slope, path=d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=None)
    ap.add_argument("--sort", choices=["em", "acc", "path"], default="path")
    a = ap.parse_args()
    os.chdir(REPO)

    rows = []
    for root in (a.root or ROOTS):
        for d in sorted(glob.glob(os.path.join(root, "*/*/run_*"))):
            r = summarise(d)
            if r:
                rows.append(r)
    if not rows:
        print("no runs with eval history found")
        return

    key = {"em": lambda r: -r["em"], "acc": lambda r: -r["acc"], "path": lambda r: r["path"]}[a.sort]
    rows.sort(key=key)

    print(f"{'EM':>7} {'tokacc':>7} {'d_acc/20k':>10} {'step':>8}  run")
    for r in rows:
        slope = "     -" if r["slope"] != r["slope"] else f"{r['slope']:+9.2f}"
        print(f"{r['em']:7.2f} {r['acc']:7.2f} {slope} {r['step']:8d}  {r['path']}")
    print(f"\n{len(rows)} runs.  climbing = |d_acc/20k| > ~1.0 => not converged, number is a lower bound")


main()
