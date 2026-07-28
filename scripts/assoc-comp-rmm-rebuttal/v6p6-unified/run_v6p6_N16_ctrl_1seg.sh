#!/bin/bash
set -e

# ── STAGE 1 / CONTROL: v6p6 identity (M == T) at the paper's identity segmentation
#
# WHY THIS RUN EXISTS
# Every v5p7 identity number at N16 in Table 2 was produced at tps=112 / pps=16 --
# the WHOLE 16-pair context in ONE segment, memory crossing a single boundary
# (context -> question). Grep runs-rmmv5p7/N16-*: there is not one identity run at
# tps=7. The compressed numbers (v5p4 unpool->pool, 55.08) are at tps=7, i.e. 16
# segments. So "identity 98.5 vs compressed 55.1" also differs in segmentation, and
# no existing run separates the two axes.
#
# v6p6 is the only version that can, because identity is not a mode here: it is
# NUM_MEMORY_VECTORS == T. Omitting --num_memory_vectors gives M = T at whatever
# tps is set, from ONE weight set. This script is the M/T = 1 anchor at tps=112.
#
# PASS CONDITION (this is a gate, not a result)
#   v5p7 identity, ss32/H1/lr1e-4, N16, tps=112:  97.96 and 99.02 EM
#   This must land in the same place. If it plateaus near ~50 like the tps=7 runs
#   already did, the unified path has a defect and NOTHING downstream of it is
#   interpretable -- stop and debug rather than running the ratio sweep.
#
# Watch eval_token_accuracy, not exact_match: across every run in the grid
# EM ~= tokacc^2 (value-token errors are independent), so EM squares away the
# signal you need to call this early.
#
# Env overrides (used by launch_v6p6_workers.sh to slice work):
#   RUNS="1 2"      seed indices  (seed = 142 + N)
#   LRS="1e-04"     learning rates
#
# Usage:
#   CUDA_VISIBLE_DEVICES=0 RUNS="1 2" LRS="1e-04" ./run_v6p6_N16_ctrl_1seg.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model (matched to the v5p7 identity cell that reached 97.96 / 99.02) ────
L=4
H=1                       # NB: H=4 costs ~55 EM on the same v5p7 cell (81.68 vs 97.96)
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32             # per-layer GDN state fixed at 128; do NOT raise, it
                          # invalidates the GDN/mamba baselines without a re-run

# ── memory mechanism ───────────────────────────────────────────────────────
WRITE_MODE=pool
READ_MODE=unpool
IDENTITY_INIT=True        # ReZero copy-init: write starts as token i -> slot i

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
N_PAIRS=16
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# ── segmentation: whole context in one segment (== v5p7 pps16 identity cell) ─
TOKENS_PER_SEGMENT=$((N_PAIRS * 7))     # 112
MAX_MEMORY_VECTORS=112                  # bank capacity must be >= T for M == T

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

USE_PARALLEL_PREFILL=True
THREAD_MEMORY=True

for LR in ${LRS:-1e-04 3e-04}; do
  for N in ${RUNS:-1 2}; do

    RUN_NAME="rmmv6p6_${WRITE_MODE}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}"
    RUN_NAME="${RUN_NAME}_cap${MAX_MEMORY_VECTORS}_Midentity_lr${LR}_bs${TBS}_tps${TOKENS_PER_SEGMENT}_id_init"
    EXP_PATH="./runs-rebuttal/rmmv6p6-unified/${DATA_PATH}/${RUN_NAME}/run_${N}"
    if [ -d "$EXP_PATH" ]; then
      echo "Skipping existing: $EXP_PATH"
      continue
    fi

    echo "Launching: $EXP_PATH"
    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmm_on_kv_retrieval-v6p6.py \
      --exp_path                    "$EXP_PATH" \
      --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
      --gradient_accumulation_steps $GRAD_ACC_STEPS \
      --total_batch_size            $TBS \
      --data_path                   "./data/${DATA_PATH}" \
      --tokenizer_path              "$TOKENIZER_PATH" \
      --base_model                  $BASE_MODEL \
      --n_layer                     $L \
      --n_head                      $H \
      --n_embd                      $D \
      --fla_layer                   $FLA_LAYER \
      --state_size                  $STATE_SIZE \
      --expand_v                    $EXPAND_V \
      --conv_kernel                 $CONV_KERNEL \
      --max_memory_vectors          $MAX_MEMORY_VECTORS \
      --write_mode                  $WRITE_MODE \
      --read_mode                   $READ_MODE \
      --thread_memory               $THREAD_MEMORY \
      --use_parallel_prefill        $USE_PARALLEL_PREFILL \
      --tokens_per_segment          $TOKENS_PER_SEGMENT \
      --identity_init               $IDENTITY_INIT \
      --n_pairs                     $N_PAIRS \
      --n_keys                      $K \
      --n_values                    $V \
      --learning_rate               $LR \
      --max_steps                   $ITERS \
      --warmup_steps                $WARMUP \
      --eval_steps                  $EVAL_STEPS \
      --logging_steps               $EVAL_STEPS \
      --early_stopping_patience     $EARLY_STOP \
      --seed                        $((142 + N))
      # NB: --num_memory_vectors deliberately OMITTED => None => M = T = 112.
  done
done

echo "ctrl_1seg worker done (RUNS='${RUNS:-1 2}' LRS='${LRS:-1e-04 3e-04}')"
