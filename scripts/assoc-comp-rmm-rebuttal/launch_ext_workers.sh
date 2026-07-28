#!/bin/bash
# Extend the compressed-RMM (pool/unpool) Table-2 cells past their 200k budget.
#
# WHY: every pool cell was still climbing when its 200k budget ran out, and the
# schedule is constant_with_warmup (LR never decays), so resuming is a pure
# continuation. Measured escape steps: 26.5k / 118.5k (1-pair N16), 89.5k / 125k
# (4-pair N8), never (4-pair N16) -- vs 3.5-4.5k for GDN. The reported 55.1 /
# 67.7 / 4.8 are truncation artifacts, not capacity ceilings.
#
# One worker per cell, 6 total on GPU1. Each resumes to 400k steps.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

LOGDIR="./logs-pool-ext"; mkdir -p "$LOGDIR"
GPU=${GPU:-1}
ITERS=${ITERS:-400000}

R7="runs-rmmv5p4/N16-K2V2-V62_1M/rmmv5p4_GatedDeltaNet_llama_L4H1D128_ss32_M8_unpool_pool_lr1e-04_bs64_pps1_tps7"
R28a="runs-rmmv5p4/N8-K2V2-V62_1M/rmmv5p4_GatedDeltaNet_llama_L4H4D128_ss32_M16_unpool_pool_lr3e-04_bs64_pps4_tps28"
R28b="runs-rmmv5p4/N16-K2V2-V62_1M/rmmv5p4_GatedDeltaNet_llama_L4H4D128_ss32_M16_unpool_pool_lr3e-04_bs64_pps4_tps28"

spawn () {  # spawn <name> <src_run_dir>
  local name="$1" src="$2"
  local log="$LOGDIR/${name}.out"
  echo "  -> $name  GPU$GPU  $src"
  env CUDA_VISIBLE_DEVICES="$GPU" nohup setsid \
      "$HOME/envs/mamba2/bin/python" "$SCRIPT_DIR/extend_pool_run.py" \
      --iters "$ITERS" "$src" > "$log" 2>&1 &
  echo "     pid $!   log $log"
}

case "${1:-}" in
  go)
    echo "EXTENSION — 6 cells -> ${ITERS} steps"
    spawn E1-1pair-N16-s143  "$R7/run_1"
    spawn E2-1pair-N16-s144  "$R7/run_2"
    spawn E3-4pair-N8-s143   "$R28a/run_1"
    spawn E4-4pair-N8-s144   "$R28a/run_2"
    spawn E5-4pair-N16-s143  "$R28b/run_1"
    spawn E6-4pair-N16-s144  "$R28b/run_2"
    ;;
  status)
    nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
    for d in runs-rebuttal/rmmv5p4ext/*/*/run_*; do
      [ -d "$d" ] || continue
      last=$(ls -d "$d"/checkpoint-* 2>/dev/null | sed 's/.*-//' | sort -n | tail -1)
      echo "  step=${last:-0}  $(echo "$d" | sed 's|runs-rebuttal/rmmv5p4ext/||')"
    done
    ;;
  stop) pkill -f extend_pool_run.py; pkill -f run_rmm_on_kv_retrieval-v5p4.py ;;
  *) echo "usage: $0 {go|status|stop}"; exit 1 ;;
esac
