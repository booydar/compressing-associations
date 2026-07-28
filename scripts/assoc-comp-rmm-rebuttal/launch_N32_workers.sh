#!/bin/bash
# Staged launcher for the N32 token-level worker pool.
#
# DESIGN: a FIXED pool of workers, each draining an ordered queue sequentially.
# Past GPU saturation total throughput is roughly conserved, so adding concurrent
# jobs does not finish anything sooner — it delays every result equally, including
# the decisive one. Observed: 2 concurrent jobs already push utilisation to 50-85%,
# so ~3-4 per GPU is the ceiling.
#
# OCCUPANCY: both GPUs were freed 2026-07-25 (v6p6 sweep and the two pool-1tps
# runs stopped), so the full pool lands 3 workers per GPU — at the low end of the
# 3-4 ceiling, with no pre-existing tenants to contend with.
#
#   GPU0: W1 warmstart-s144, W2 warmstart-s143, W5 seeds-7-8
#   GPU1: W3 seeds-3-4,      W4 seeds-5-6,      W6 gdn-seeds
#
# The two warm-starts are deliberately co-located on GPU0: they are the decisive
# experiment, they are short (2 cells x 60k steps from a converged model), and
# when they finish GPU0 drops to a single tenant, which speeds up whatever is
# still draining there.
#
# STAGE 1: the two warm-starts + one seed-sweep worker (3 jobs). Fast readout,
#   and lets you watch utilisation before committing the rest.
# STAGE 2: the remaining workers. stage1 + stage2 = the balanced 3/3 above.
# ALL:     both stages at once.
#
# Usage:
#   ./launch_N32_workers.sh stage1
#   ./launch_N32_workers.sh stage2
#   ./launch_N32_workers.sh all
#   ./launch_N32_workers.sh status
#
# Nothing is killed automatically. To free GPU1 first:
#   pkill -f run_rmm_on_kv_retrieval-v6p6.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

LOGDIR="./logs-N32-workers"
mkdir -p "$LOGDIR"

# spawn <logname> <gpu> <script> [VAR=val ...]
spawn () {
  local name="$1" gpu="$2" script="$3"; shift 3
  local log="$LOGDIR/${name}.out"
  echo "  -> $name  GPU$gpu  $script  ${*:-}"
  env CUDA_VISIBLE_DEVICES="$gpu" "$@" \
      nohup setsid "$SCRIPT_DIR/$script" > "$log" 2>&1 &
  echo "     pid $!   log $log"
}

case "${1:-}" in
  stage1|all)
    echo "STAGE 1 — warm-starts (GPU0) + first seed slice (GPU1)"
    spawn W1-warmstart-s144 0 run_rmm_v5p7_N32_warmstart-s144.sh
    spawn W2-warmstart-s143 0 run_rmm_v5p7_N32_warmstart-s143.sh
    spawn W3-seeds-3-4      1 run_rmm_v5p7_N32_seedsweep.sh RUNS="3 4"
    [ "$1" = "all" ] || exit 0
    echo
    ;;&
  stage2|all)
    echo "STAGE 2 — remaining seed slices + GDN contrast (final layout 3/3)"
    spawn W4-seeds-5-6 1 run_rmm_v5p7_N32_seedsweep.sh RUNS="5 6"
    spawn W5-seeds-7-8 0 run_rmm_v5p7_N32_seedsweep.sh RUNS="7 8"
    spawn W6-gdn-seeds 1 run_gdn_N32_seedsweep.sh      RUNS="3 4 5 6"
    ;;
  status)
    nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
    echo "--- worker trainings ---"
    ps -eo pid,etime,cmd \
      | grep -E "run_rmm_on_kv_retrieval-v5p7\.py|run_fla_on_kv_retrieval-default\.py" \
      | grep -v grep | cut -c1-160
    ;;
  *)
    echo "usage: $0 {stage1|stage2|all|status}"
    exit 1
    ;;
esac
