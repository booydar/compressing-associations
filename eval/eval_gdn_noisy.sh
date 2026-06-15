#!/bin/bash
# Evaluate one trained GDN run on noisy-AR at total_noise_blocks ∈ {4,8,16,32,64,128}.
#
# Usage:
#   bash eval/eval_gdn_noisy.sh <run_dir> [extra args to run_eval_sweep.py]
#
# Example:
#   bash eval/eval_gdn_noisy.sh \
#       runs-noisy-ar/N4-K2V2-V62_K1-vary-B7_1M/gdn_gated_delta_net_L4H4D128_ss32_ck4_lr1e-03_bs64/run_1
#
# Env:
#   NB_LIST   (default 4,8,16,32,64,128)
#   N_VALID   (default 2000)
#   BS        (default 32)
#   PYTHON    (default = current python)
#   FORCE=1   (re-run even if metrics.json exists)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

[ -n "$1" ] || { echo "usage: $0 <run_dir> [extra args]"; exit 1; }
RUN_DIR="$1"; shift

PYTHON=${PYTHON:-python}
NB_LIST=${NB_LIST:-"4,8,16,32,64,128"}
N_VALID=${N_VALID:-2000}
BS=${BS:-32}
FORCE_FLAG=$( [ -n "$FORCE" ] && echo "--force" || echo "" )

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
ulimit -n 65536 2>/dev/null || true

"$PYTHON" eval/run_eval_sweep.py \
  --run_dir "$RUN_DIR" \
  --model gdn \
  --nb_list "$NB_LIST" \
  --n_valid "$N_VALID" \
  --per_device_batch_size "$BS" \
  --python "$PYTHON" \
  $FORCE_FLAG "$@"
