#!/usr/bin/env python3
"""Extend a finished v6p6 run by resuming its full training state.

Generalised from extend_pool_run.py (which is hardwired to runs-rmmv5p4 and the
v5p4 runner). Same contract: the run is copied to runs-rebuttal/<ext_root>/ first,
newest checkpoint only, so the original is never written to; the command is
reconstructed from the run's own config.json["cli_args"], so nothing about the
config can drift.

lr_scheduler_type is constant_with_warmup in every one of these runs -- the LR
never decays -- so raising max_steps and resuming is a pure continuation, not a
restart under a different schedule.

WHY YOU WOULD RUN THIS
The two v6p6 M=7 / tps=7 arms were still climbing when they were stopped:

    lr 3e-04  run_1   EM 50.94  tokacc 70.95  @198.5k   (43.7 -> 50.9 over the last 58k)
    lr 1e-04  run_1   EM 44.60  tokacc 66.51  @195k     (escaped ~100k, steeper slope)

They are the tps=7 endpoint of the segmentation ladder. Extending them to 400k
costs two workers and firms up the one rung that is already paid for. It is NOT a
substitute for the ctrl run -- extending an arm that plateaus near 50 will not
produce 98.

PREREQUISITE
run_rmm_on_kv_retrieval-v6p6.py has no `checkpoint` field and calls trainer.train()
with no arguments, so it cannot resume. Apply v6p6_add_resume.patch first (two
hunks, both copied verbatim from run_rmm_on_kv_retrieval-v5p4.py lines 258-260 and
463-470). This script checks for the field and refuses to run without it.

Usage:
    ./extend_v6p6_run.py --dry \\
        runs-rmmv6p6/N16-K2V2-V62_1M/rmmv6p6_pool_llama_L4H1D128_ss32_cap32_M7_lr3e-04_bs64_tps7_id_init/run_1
    ./extend_v6p6_run.py --iters 400000 <src_run_dir> [<src_run_dir> ...]
"""
import argparse, glob, json, os, re, shutil, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
EXT_ROOT = "runs-rebuttal/rmmv6p6ext"
RUNNER = "run_rmm_on_kv_retrieval-v6p6.py"
PY = os.path.expanduser("~/envs/mamba2/bin")

# cli_args keys that are not runner flags, or that we override
SKIP = {"exp_path", "max_steps", "checkpoint"}
# keys that are legitimately None and must be dropped rather than stringified.
# num_memory_vectors is None for identity (M == T) runs -- passing "None" through
# would be parsed as the string and break the run, so it MUST stay in this set.
NULLABLE = {"write_value_dim", "memory_task", "model_cpt", "num_memory_vectors",
            "num_read_vectors", "num_compress_heads", "max_memory_vectors"}


def newest_ckpt(d):
    cks = [c for c in glob.glob(os.path.join(d, "checkpoint-*")) if c.rsplit("-", 1)[1].isdigit()]
    return max(cks, key=lambda p: int(p.rsplit("-", 1)[1])) if cks else None


def check_runner_supports_resume():
    src = open(os.path.join(REPO, RUNNER)).read()
    if not re.search(r"^\s*checkpoint:\s*Optional\[str\]", src, re.M):
        sys.exit(
            f"{RUNNER} has no `checkpoint` field -- it cannot resume.\n"
            f"Apply scripts/assoc-comp-rmm-rebuttal/v6p6-unified/v6p6_add_resume.patch first."
        )
    if re.search(r"^\s*trainer\.train\(\s*\)\s*$", src, re.M):
        sys.exit(
            f"{RUNNER} still calls trainer.train() with no resume argument.\n"
            f"The second hunk of v6p6_add_resume.patch has not been applied."
        )


def stage(src, dry=False):
    """Copy src -> ext dir (newest checkpoint only). Returns (ext_dir, resume_step).

    With dry=True nothing is copied -- a --dry run must not leave ~18MB of staged
    checkpoints behind just to print a command.
    """
    rel = src.rstrip("/")
    for pre in ("runs-rmmv6p6/", "./runs-rmmv6p6/", "runs-rebuttal/rmmv6p6-unified/"):
        if rel.startswith(pre):
            rel = rel[len(pre):]
            break
    ext = os.path.join(EXT_ROOT, rel)
    ck = newest_ckpt(src)
    if ck is None:
        sys.exit(f"no checkpoint in {src}")
    step = int(ck.rsplit("-", 1)[1])

    if os.path.isdir(ext) and newest_ckpt(ext):
        print(f"[stage] already staged: {ext} (resume @{newest_ckpt(ext)})")
        return ext, step
    if dry:
        print(f"[stage] DRY: would copy {ck} -> {ext}/")
        return ext, step
    os.makedirs(ext, exist_ok=True)
    for f in ("config.json",):
        p = os.path.join(src, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(ext, f))
    dst_ck = os.path.join(ext, os.path.basename(ck))
    if not os.path.isdir(dst_ck):
        print(f"[stage] copying {ck} -> {dst_ck}")
        shutil.copytree(ck, dst_ck)
    return ext, step


def build_cmd(ext, iters, cfg_dir=None):
    cfg = json.load(open(os.path.join(cfg_dir or ext, "config.json")))["cli_args"]
    cmd = [os.path.join(PY, "accelerate"), "launch",
           "--main_process_port", "0", "--num_processes", "1",
           "--mixed_precision", "bf16", "--config_file", "accelerate.yaml",
           RUNNER,
           "--exp_path", ext,
           "--max_steps", str(iters),
           "--checkpoint", "latest"]
    for k, v in cfg.items():
        if k in SKIP:
            continue
        if v is None:
            if k in NULLABLE:
                continue
            sys.exit(f"unexpected null for {k} -- add it to NULLABLE if that is correct")
        cmd += [f"--{k}", str(v)]
    return cmd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--iters", type=int, default=400000)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    os.chdir(REPO)
    if not a.dry:
        check_runner_supports_resume()
    for src in a.runs:
        ext, step = stage(src, dry=a.dry)
        if step >= a.iters:
            print(f"[skip] {ext} already at {step} >= {a.iters}")
            continue
        cmd = build_cmd(ext, a.iters, cfg_dir=src if a.dry else None)
        print(f"[extend] {ext}  {step} -> {a.iters}")
        if a.dry:
            print("   " + " ".join(cmd))
            continue
        rc = subprocess.call(cmd)
        print(f"[done] {ext} rc={rc}")
    print("queue drained")


main()
