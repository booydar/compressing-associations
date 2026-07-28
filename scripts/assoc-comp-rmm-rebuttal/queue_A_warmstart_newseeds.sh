#!/bin/bash
# QUEUE A (rev 2, 2026-07-28) -- warm start on NEW SEEDS, compute-matched.
#
# REV 1 FAILED and why: the N16 source was given only 30k steps on the
# assumption (from a single logged trajectory, "0.86 @ 10k") that N16 converges
# fast. Seed 145 never escaped the chance plateau in 30k -- it ended at
# EM 0.0698 / token_acc 0.5067, dead flat -- so stage 2 was warm-starting from
# a source that had learned nothing, and duly sat at EM 0.03. Escape time is
# highly seed-dependent (15.5k to >67k observed at N32), so a fixed short
# budget at the LOW source LR was the wrong bet.
#
# REV 2 fix: source LR 3e-04 instead of 1e-04 (faster escape; queue B has
# already shown a 3e-04 source warm-starts to 0.951, so it is a valid source),
# and 60k source steps instead of 30k. Compute story is unchanged and still
# favourable: 60k source + 60k target = 120k < the 200k from-scratch budget.
#
# Seed 147 dropped for time; 2 new seeds takes n from 2 to 4.
#
# NOTE the rev-1 run is a free NEGATIVE CONTROL, worth a sentence in the paper:
# warm starting from a source that never learned does NOT rescue N32 (0.03).
# The benefit comes from the source having a live memory store, not merely from
# being initialised at something other than random.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
mkdir -p logs-warmstart
for SEED in 145 146; do
  echo "########## QUEUE A: seed $SEED stage 1 (N16 source, lr3e-04, 60k) ##########"
  CUDA_VISIBLE_DEVICES=1 SEED=$SEED LR=3e-04 ITERS=60000 \
    bash scripts/assoc-comp-rmm-rebuttal/run_rmm_v5p7_N16_src_param.sh \
    > logs-warmstart/A_n16src_s${SEED}.out 2>&1
  echo "########## QUEUE A: seed $SEED stage 2 (N32 warm start, 60k) ##########"
  CUDA_VISIBLE_DEVICES=1 SEED=$SEED SRC_LR=3e-04 LRS="3e-04" ITERS=60000 \
    bash scripts/assoc-comp-rmm-rebuttal/run_rmm_v5p7_N32_warmstart_param.sh \
    > logs-warmstart/A_ws_s${SEED}.out 2>&1
  echo "########## QUEUE A: seed $SEED DONE ##########"
done
echo "QUEUE A finished"
