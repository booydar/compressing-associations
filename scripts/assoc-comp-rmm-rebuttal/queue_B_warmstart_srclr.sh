#!/bin/bash
# QUEUE B (second priority) -- does the rescue depend on WHICH N16 checkpoint
# we bootstrap from? No prerequisite: all six N16 tps7 sources already exist and
# are converged (EM 0.987-0.992), but every warm-start run so far used
# SRC_LR=1e-04. If a reviewer asks "did you pick a lucky source checkpoint?",
# there is currently no answer. Four cells: src {3e-04, 5e-05} x seed {143,144},
# target lr 3e-04, same 60k budget as the existing cells so they are comparable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
mkdir -p logs-warmstart
for SRC_LR in 3e-04 5e-05; do
  for SEED in 144 143; do   # 144 first: the seed that collapses from scratch everywhere
    echo "########## QUEUE B: src $SRC_LR seed $SEED ##########"
    CUDA_VISIBLE_DEVICES=1 SEED=$SEED SRC_LR=$SRC_LR LRS="3e-04" ITERS=60000 \
      bash scripts/assoc-comp-rmm-rebuttal/run_rmm_v5p7_N32_warmstart_param.sh \
      > logs-warmstart/B_ws_src${SRC_LR}_s${SEED}.out 2>&1
  done
done
echo "QUEUE B finished"
