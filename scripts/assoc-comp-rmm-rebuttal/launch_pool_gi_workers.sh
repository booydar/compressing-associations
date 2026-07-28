#!/bin/bash
# Worker pool for the compressed-RMM (pool/unpool) gate-init sweep, GPU1 only.
#
# DESIGN: 4 fixed workers, each draining an ordered queue sequentially. Past GPU
# saturation total throughput is roughly conserved, so more concurrency does not
# finish anything sooner. Measured on this config: 7.3 steps/s solo, ~4 steps/s
# with 4 tenants => ~7 h per 100k-step cell.
#
# STAGE A1 (the screen, N=16 tps7): a 2x2 over
#   M in {8, 32}  x  gate_init in {none, both}, at lr1e-4, H=1/ss32.
# M=8 is the current table's best (55.1 EM) but its read bottleneck caps it near
# ~55; M=32 has the readout capacity but has never trained (0.066/0.092). If the
# open-gate init does anything useful, M=32 is where it shows.
# Each queue runs seed 143 first, then seed 144 — the second cell is worth having
# under every outcome, so no worker idles while the screen is being read.
#
# Usage:  ./launch_pool_gi_workers.sh a1 | status | stop

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

LOGDIR="./logs-pool-gi"
GPU=${GPU:-1}
mkdir -p "$LOGDIR"

spawn () {  # spawn <name> <cells...>
  local name="$1"; shift
  local log="$LOGDIR/${name}.out"
  echo "  -> $name  GPU$GPU  [$*]"
  env CUDA_VISIBLE_DEVICES="$GPU" CELLS="$*" \
      nohup setsid "$SCRIPT_DIR/run_rmm_v5p4gi_pool.sh" > "$log" 2>&1 &
  echo "     pid $!   log $log"
}

case "${1:-}" in
  a1)
    echo "STAGE A1 — 2x2 screen (M x gate_init) at N=16 tps7, 2 seeds each"
    spawn W1-M8-none   16:7:8:1e-04:none:1  16:7:8:1e-04:none:2
    spawn W2-M8-both   16:7:8:1e-04:both:1  16:7:8:1e-04:both:2
    spawn W3-M32-none  16:7:32:1e-04:none:1 16:7:32:1e-04:none:2
    spawn W4-M32-both  16:7:32:1e-04:both:1 16:7:32:1e-04:both:2
    ;;
  status)
    nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
    echo "--- workers ---"
    ps -eo pid,etime,cmd | grep "run_rmm_on_kv_retrieval-v5p4gi.py" | grep -v grep \
      | sed -E 's/.*--exp_path ([^ ]+).*/\1/' | sed 's|./runs-rebuttal/rmmv5p4gi/||'
    echo "--- progress ---"
    for d in runs-rebuttal/rmmv5p4gi/*/*/run_*; do
      [ -d "$d" ] || continue
      last=$(ls -d "$d"/checkpoint-* 2>/dev/null | sed 's/.*-//' | sort -n | tail -1)
      echo "  ${last:-0}  $(echo "$d" | sed 's|runs-rebuttal/rmmv5p4gi/||')"
    done
    ;;
  stop)
    pkill -f "run_rmm_on_kv_retrieval-v5p4gi.py" && echo "stopped" || echo "nothing running"
    ;;
  *) echo "usage: $0 {a1|status|stop}"; exit 1 ;;
esac
