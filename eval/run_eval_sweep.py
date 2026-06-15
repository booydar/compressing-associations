"""Run the noisy-AR eval sweep for one training run dir.

Reads <run_dir>/config.json to recover the training cli_args, then iterates
total_noise_blocks ∈ NB_LIST and, for each:
  1. builds data/N{N}-K2V2-V62_NB{NB}-B{B}_eval{N_VALID} if missing
  2. launches the model-specific eval script (eval/eval_<model>.py) with
     --model_cpt <run_dir> --data_path <eval_dataset>
     --predictions_out <run_dir>/eval_noisy/NB{NB}/predictions.jsonl
     --metrics_out <run_dir>/eval_noisy/NB{NB}/metrics.json
     + every relevant model arg copied from the training config.

Skips noise levels whose metrics.json already exists, unless --force.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # .../remote
DEFAULT_NB_LIST = [4, 8, 16, 32, 64, 128]

# Which cli_args (from config.json) to forward to each model's eval script.
ARG_PASSTHROUGH = {
    "gdn": [
        "tokenizer_path", "base_model",
        "n_layer", "n_head", "n_embd",
        "state_size", "conv_kernel",
        "n_pairs", "n_keys", "n_values",
    ],
    "armt": [
        "tokenizer_path", "base_model",
        "n_layer", "n_head", "n_embd",
        "n_mem_tokens", "n_ctrl_tokens", "d_mem", "correction",
        "tokens_per_segment", "pairs_per_segment",
        "memory_task_freq", "memory_task", "memory_key_size", "memory_value_size",
        "n_pairs", "n_keys", "n_values",
    ],
    "rmm": [
        "tokenizer_path", "base_model",
        "n_layer", "n_head", "n_embd",
        "fla_layer", "state_size", "expand_v", "conv_kernel", "use_short_conv",
        "num_memory_vectors", "write_mode", "read_mode",
        "write_value_dim", "num_memory_heads", "use_parallel_prefill",
        "tokens_per_segment",
        "memory_task_freq", "memory_task", "memory_key_size", "memory_value_size",
        "n_pairs", "n_keys", "n_values",
    ],
}

EVAL_SCRIPT = {
    "gdn":  "eval/eval_fla.py",
    "armt": "eval/eval_armt.py",
    "rmm":  "eval/eval_rmm_v5p4.py",
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--run_dir", required=True,
                   help="training run dir (contains config.json + checkpoint-*)")
    p.add_argument("--model", required=True, choices=list(EVAL_SCRIPT.keys()))
    p.add_argument("--nb_list", type=str, default=",".join(map(str, DEFAULT_NB_LIST)),
                   help="comma-separated total_noise_blocks values")
    p.add_argument("--n_valid", type=int, default=2000)
    p.add_argument("--noise_block_size", type=int, default=7)
    p.add_argument("--per_device_batch_size", type=int, default=32)
    p.add_argument("--force", action="store_true",
                   help="re-run even if metrics.json already exists")
    p.add_argument("--launcher", default="accelerate",
                   choices=["accelerate", "python"],
                   help="how to launch eval (accelerate launch vs plain python)")
    p.add_argument("--mixed_precision", default="bf16")
    p.add_argument("--python", default=sys.executable,
                   help="python interpreter to use")
    return p.parse_args()


def load_train_cfg(run_dir: Path) -> dict:
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"missing {cfg_path}")
    with open(cfg_path) as f:
        return json.load(f).get("cli_args", {})


def ensure_eval_dataset(n_pairs: int, nb: int, n_valid: int, B: int,
                       python: str) -> Path:
    out = REPO_ROOT / f"data/N{n_pairs}-K2V2-V62_NB{nb}-B{B}_eval{n_valid}"
    if out.exists():
        return out
    print(f"[build] {out}")
    subprocess.run([
        python, "eval/build_eval_dataset.py",
        "--n_pairs", str(n_pairs),
        "--total_noise_blocks", str(nb),
        "--noise_block_size", str(B),
        "--n_valid", str(n_valid),
        "--out_path", str(out),
    ], check=True, cwd=str(REPO_ROOT))
    return out


def build_eval_cmd(args, model: str, train_cfg: dict, eval_data: Path,
                   noise_out_dir: Path) -> list:
    if args.launcher == "accelerate":
        cmd = [
            "accelerate", "launch",
            "--main_process_port", "0",
            "--num_processes", "1",
            "--mixed_precision", args.mixed_precision,
            "--config_file", "accelerate.yaml",
        ]
    else:
        cmd = [args.python]
    cmd += [
        EVAL_SCRIPT[model],
        "--model_cpt", args.run_dir,
        "--data_path", str(eval_data),
        "--exp_path", str(noise_out_dir),
        "--predictions_out", str(noise_out_dir / "predictions.jsonl"),
        "--metrics_out", str(noise_out_dir / "metrics.json"),
        "--per_device_batch_size", str(args.per_device_batch_size),
    ]
    for k in ARG_PASSTHROUGH[model]:
        v = train_cfg.get(k)
        if v is None:
            continue
        cmd += [f"--{k}", str(v)]
    return cmd


def main():
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"--run_dir not a directory: {run_dir}")
    train_cfg = load_train_cfg(run_dir)

    # Auto-detect n_pairs from training data_path or n_pairs cli arg.
    n_pairs = train_cfg.get("n_pairs")
    if not n_pairs:
        dp = train_cfg.get("data_path", "")
        import re
        m = re.search(r"/N(\d+)-", dp) or re.search(r"^N(\d+)-", dp.lstrip("./"))
        if m:
            n_pairs = int(m.group(1))
        else:
            raise SystemExit(f"could not detect n_pairs from cfg; data_path={dp}")
    n_pairs = int(n_pairs)
    print(f"[info] run_dir={run_dir}")
    print(f"[info] model={args.model}  n_pairs={n_pairs}  bs={args.per_device_batch_size}")

    nb_list = [int(x) for x in args.nb_list.split(",") if x.strip()]
    for nb in nb_list:
        noise_out_dir = run_dir / "eval_noisy" / f"NB{nb}"
        metrics_path = noise_out_dir / "metrics.json"
        if metrics_path.exists() and not args.force:
            print(f"[skip] {metrics_path} already exists (use --force to re-run)")
            continue
        noise_out_dir.mkdir(parents=True, exist_ok=True)

        eval_data = ensure_eval_dataset(
            n_pairs=n_pairs, nb=nb,
            n_valid=args.n_valid, B=args.noise_block_size,
            python=args.python,
        )
        cmd = build_eval_cmd(args, args.model, train_cfg, eval_data, noise_out_dir)
        print(f"[run] NB={nb}  →  {noise_out_dir}")
        print("       " + " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))

    print("[done]")


if __name__ == "__main__":
    main()
