#!/bin/bash
# Evaluate one trained RMM v5p4 run on noisy-AR at total_noise_blocks ∈ {4,8,16,32,64,128}.
#
# Usage:
#   bash eval/eval_rmm_v5p4_noisy.sh <run_dir> [extra args to run_eval_sweep.py]
#
# Example:
#   bash eval/eval_rmm_v5p4_noisy.sh \
#       runs-noisy-ar/N4-K2V2-V62_K1-vary-B7_1M/rmmv5p4_GatedDeltaNet_llama_L4H4D128_ss32_M4_unpool_pool_lr3e-04_bs64_pps1_tps7/run_1
#
# Env: NB_LIST, N_VALID, BS, PYTHON, FORCE=1  (see eval_gdn_noisy.sh).
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

# Pin to a single GPU. With num_processes=1 and >1 visible CUDA device,
# HF Trainer auto-wraps eval in nn.DataParallel, which breaks the custom
# segmented forward (StopIteration in replica 1).
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}

# Many-segment batches at high NB can blow through the open-files limit.
ulimit -n 65536 2>/dev/null || true

"$PYTHON" eval/run_eval_sweep.py \
  --run_dir "$RUN_DIR" \
  --model rmm \
  --nb_list "$NB_LIST" \
  --n_valid "$N_VALID" \
  --per_device_batch_size "$BS" \
  --python "$PYTHON" \
  $FORCE_FLAG "$@"
