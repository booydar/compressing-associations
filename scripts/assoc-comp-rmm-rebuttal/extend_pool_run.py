#!/usr/bin/env python3
"""Extend a finished compressed-RMM run by resuming its full training state.

Every pool/unpool cell in Table 2 was still improving when its 200k-step budget
ran out, and the LR schedule is `constant_with_warmup` -- the LR never decays --
so raising max_steps and resuming is a pure continuation, not a restart with a
different schedule.

The run is copied to runs-rebuttal/rmmv5p4ext/<same relative path> first so the
original (which backs published numbers) is never written to. Only the newest
checkpoint is copied; that is all HF Trainer needs to resume.

Usage:
    extend_pool_run.py <src_run_dir> [<src_run_dir> ...] --iters 400000
"""
import argparse, glob, json, os, shutil, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT_ROOT = "runs-rebuttal/rmmv5p4ext"
PY = os.path.expanduser("~/envs/mamba2/bin")

# cli_args keys that are not runner flags, or that we override / must skip when null
SKIP = {"exp_path", "max_steps"}
NULLABLE = {"write_value_dim", "memory_task", "model_cpt"}


def newest_ckpt(d):
    cks = [c for c in glob.glob(os.path.join(d, "checkpoint-*")) if c.rsplit("-", 1)[1].isdigit()]
    return max(cks, key=lambda p: int(p.rsplit("-", 1)[1])) if cks else None


def stage(src, iters):
    """Copy src -> ext dir (newest checkpoint only). Returns (ext_dir, resume_step)."""
    rel = src.rstrip("/")
    for pre in ("runs-rmmv5p4/", "./runs-rmmv5p4/"):
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
    os.makedirs(ext, exist_ok=True)
    for f in ("config.json",):
        if os.path.exists(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), os.path.join(ext, f))
    dst_ck = os.path.join(ext, os.path.basename(ck))
    if not os.path.isdir(dst_ck):
        print(f"[stage] copying {ck} -> {dst_ck}")
        shutil.copytree(ck, dst_ck)
    return ext, step


def build_cmd(ext, iters):
    cfg = json.load(open(os.path.join(ext, "config.json")))["cli_args"]
    cmd = [os.path.join(PY, "accelerate"), "launch",
           "--main_process_port", "0", "--num_processes", "1",
           "--mixed_precision", "bf16", "--config_file", "accelerate.yaml",
           "run_rmm_on_kv_retrieval-v5p4.py",
           "--exp_path", ext,
           "--max_steps", str(iters),
           "--checkpoint", "latest"]
    for k, v in cfg.items():
        if k in SKIP:
            continue
        if v is None:
            if k in NULLABLE:
                continue
            sys.exit(f"unexpected null for {k}")
        cmd += [f"--{k}", str(v)]
    return cmd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--iters", type=int, default=400000)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    os.chdir(REPO)
    for src in a.runs:
        ext, step = stage(src, a.iters)
        if step >= a.iters:
            print(f"[skip] {ext} already at {step} >= {a.iters}")
            continue
        cmd = build_cmd(ext, a.iters)
        print(f"[extend] {ext}  {step} -> {a.iters}")
        if a.dry:
            print("   " + " ".join(cmd))
            continue
        rc = subprocess.call(cmd)
        print(f"[done] {ext} rc={rc}")
    print("queue drained")


main()
