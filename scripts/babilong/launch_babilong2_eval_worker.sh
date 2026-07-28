#!/bin/bash
# One GPU worker for the babilong2 seg32 length-extrapolation sweep.
#
#   launch_babilong2_eval_worker.sh <gpu> <task>:<run_name_substring> [...]
#
# e.g. launch_babilong2_eval_worker.sh 0 qa1:identity_identity_mem16_lr1e-03 qa2:pool_unpool
#
# Each spec is an explicit (task, variant) pair so two workers never collide on
# the same output dir. Two passes over the assigned variants: pass 1 (1..32
# segments) is cheap and fills the whole table quickly, pass 2 adds the
# expensive 64/128/256-segment points. eval_babilong2_seg32.py skips any eval
# that already has all_results.json, so re-running a worker resumes rather than
# redoing work.
set -u
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY=${BABILONG_PYTHON:-$HOME/envs/fla/bin/python}
GPU=$1; shift
export CUDA_VISIBLE_DEVICES=$GPU

for SEGS in "1 2 4 8 16 32" "64 128 256"; do
  for spec in "$@"; do
    task=${spec%%:*}
    variant=${spec#*:}
    echo "=== GPU$GPU  $task/$variant  segments: $SEGS  ($(date)) ==="
    $PY scripts/babilong/eval_babilong2_seg32.py \
        --tasks "$task" --variants "$variant" \
        --eval-segments $SEGS --batch-size 8 --big-batch-size 8
  done
done
echo "=== GPU$GPU ALL DONE ($(date)) ==="
