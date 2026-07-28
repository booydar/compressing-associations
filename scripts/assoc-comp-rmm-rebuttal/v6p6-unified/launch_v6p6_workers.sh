#!/bin/bash
# Staged launcher for the v6p6-unified grid.
#
# DESIGN: a fixed pool of workers, each draining an ordered queue. Past GPU
# saturation total throughput is roughly conserved -- adding concurrent jobs does
# not finish anything sooner, it delays every result equally, including the
# decisive one. Stage 1 is sized so every worker holds exactly ONE run, so the
# whole gate lands at the same time rather than trickling in.
#
# PACKING. These models are tiny (L=4, d=128, ~1-2M params, batch 64), so they are
# launch-bound, not compute-bound, and pack better than the note in
# launch_N32_workers.sh (written for the same models) suggests:
#
#   tps=7  runs (armt hedge, extend): 16 sequential segments of 7 tokens => almost
#          pure kernel-launch overhead. 4 per GPU is comfortable.
#   tps=112 runs (ctrl, ratio, ladder): one segment with parallel prefill => denser
#          kernels, higher SM occupancy each. 3 per GPU.
#
# Stage 1 puts 3 tps=112 jobs on GPU0 and 3 tps=7 jobs on GPU1 for that reason.
# VERIFY, do not trust the above -- watch SM% for 60s after launch:
#     nvidia-smi dmon -s u -c 60
# If sm < 70% sustained, add a worker with the manual one-liners at the bottom.
# If sm is pinned at 100% and step-time has doubled, you are past saturation.
#
# Usage:
#   ./launch_v6p6_workers.sh stage1     # gate (ctrl) + hedge (armt seeds), 6 workers
#   ./launch_v6p6_workers.sh stage2     # ratio curve + ladder -- ONLY after ctrl passes
#   ./launch_v6p6_workers.sh status
#   ./launch_v6p6_workers.sh readout
#
# Nothing is killed automatically. Both GPUs must be free first; check `status`.
# To stop this pool:  pkill -f run_rmm_on_kv_retrieval-v6p6.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

LOGDIR="./logs-v6p6-unified"
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
  stage1)
    echo "STAGE 1 -- gate + hedge (6 workers, 1 run each, ~8h at 6-way concurrency)"
    echo
    echo "GPU0: the control. Must reach ~98 EM (v5p7 got 97.96 / 99.02 on this cell)."
    echo "      If it plateaus near 50 like the tps=7 runs, STOP -- do not run stage 2."
    spawn C1-ctrl-lr1e4-s1 0 run_v6p6_N16_ctrl_1seg.sh LRS="1e-04" RUNS="1"
    spawn C2-ctrl-lr1e4-s2 0 run_v6p6_N16_ctrl_1seg.sh LRS="1e-04" RUNS="2"
    spawn C3-ctrl-lr3e4-s1 0 run_v6p6_N16_ctrl_1seg.sh LRS="3e-04" RUNS="1"
    echo
    echo "GPU1: the hedge. Independent of v6p6 -- this is the fallback number."
    spawn H1-armt-lr1e4-s3 1 run_v6p4armt_N16_seeds.sh LRS="1e-04" RUNS="3"
    spawn H2-armt-lr1e4-s4 1 run_v6p4armt_N16_seeds.sh LRS="1e-04" RUNS="4"
    spawn H3-armt-lr3e4-s3 1 run_v6p4armt_N16_seeds.sh LRS="3e-04" RUNS="3"
    echo
    echo "Read out with: $0 readout   (watch tokacc, not EM -- EM ~= tokacc^2)"
    ;;

  stage2)
    echo "STAGE 2 -- compression-ratio curve + segmentation ladder (6 workers)"
    echo
    echo "PRECONDITION: stage-1 ctrl reached ~98. If it did not, this grid measures"
    echo "a broken path and every point on the curve is uninterpretable."
    echo
    spawn R1-ratio-M32-s1 0 run_v6p6_N16_ratio_1seg.sh MS="32" RUNS="1"
    spawn R2-ratio-M32-s2 0 run_v6p6_N16_ratio_1seg.sh MS="32" RUNS="2"
    spawn R3-ratio-M8-s1  0 run_v6p6_N16_ratio_1seg.sh MS="8"  RUNS="1"
    spawn R4-ratio-M8-s2  1 run_v6p6_N16_ratio_1seg.sh MS="8"  RUNS="2"
    spawn R5-ratio-M4-s1  1 run_v6p6_N16_ratio_1seg.sh MS="4"  RUNS="1"
    spawn R6-ladder-t56-s1 1 run_v6p6_N16_seg_ladder.sh TPSS="56" RUNS="1"
    ;;

  status)
    nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
    echo "--- worker trainings ---"
    ps -eo pid,etime,cmd \
      | grep -E "run_rmm_on_kv_retrieval-v6p6\.py|run_rmm_on_kv_retrieval-v6p4-armt\.py" \
      | grep -v grep | cut -c1-160
    ;;

  readout)
    "$SCRIPT_DIR/collect_v6p6.py"
    ;;

  *)
    echo "usage: $0 {stage1|stage2|status|readout}"
    echo
    echo "Manual one-liners (for adding a worker after checking SM%):"
    echo "  CUDA_VISIBLE_DEVICES=0 LRS=3e-04 RUNS=2 $SCRIPT_DIR/run_v6p6_N16_ctrl_1seg.sh"
    echo "  CUDA_VISIBLE_DEVICES=1 LRS=3e-04 RUNS=4 $SCRIPT_DIR/run_v6p4armt_N16_seeds.sh"
    echo "  CUDA_VISIBLE_DEVICES=1 MS=4 RUNS=2 $SCRIPT_DIR/run_v6p6_N16_ratio_1seg.sh"
    echo "  CUDA_VISIBLE_DEVICES=0 TPSS=28 RUNS=1 $SCRIPT_DIR/run_v6p6_N16_seg_ladder.sh"
    exit 1
    ;;
esac
