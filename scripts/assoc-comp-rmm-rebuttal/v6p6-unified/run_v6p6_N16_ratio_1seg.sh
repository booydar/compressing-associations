#!/bin/bash
set -e

# ── STAGE 2: compression-ratio curve at fixed segmentation (the paper figure) ─
#
# Identical to run_v6p6_N16_ctrl_1seg.sh in every respect except NUM_MEMORY_VECTORS.
# Same weight set, same code path, same state budget, same tps=112 segmentation --
# only M changes. That is the point of v6p6 and it is the one comparison the
# current grid cannot produce: every "identity vs compressed" pair in Table 2 also
# swaps the model AND the segmentation.
#
#   M = 112  ->  M/T = 1      (identity; comes from the ctrl script, don't repeat)
#   M =  32  ->  M/T = 0.29
#   M =   8  ->  M/T = 0.07
#   M =   4  ->  M/T = 0.036
#
# GATED ON STAGE 1. If the ctrl run does not reach ~98, this sweep measures a
# broken path and every point on the curve is meaningless. Do not start it early.
#
# Plot eval_token_accuracy against M/T, with EM as a secondary axis -- EM ~= tokacc^2
# throughout this grid, so tokacc is where the curve shape actually lives.
#
# PRIOR: at tps=7, M=4 (M/T=0.57) sat at exactly 0.0 EM / 1.5% tokacc for 169k
# steps -- never escaped. If that reproduces here at tps=112, the finding is that
# compression fails discontinuously rather than degrading, which is a result worth
# reporting on its own and is a much sharper claim than "55.1".
#
# Env overrides:
#   RUNS="1 2"        seed indices (seed = 142 + N)
#   MS="32 8 4"       memory sizes
#   LRS="1e-04"       learning rates
#
# Usage:
#   CUDA_VISIBLE_DEVICES=1 RUNS="1 2" MS="32" ./run_v6p6_N16_ratio_1seg.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4
H=1
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32

WRITE_MODE=pool
READ_MODE=unpool
IDENTITY_INIT=True

K=2
V=2
N_PAIRS=16
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

TOKENS_PER_SEGMENT=$((N_PAIRS * 7))     # 112, same as ctrl
MAX_MEMORY_VECTORS=112                  # same bank capacity as ctrl -- do not
                                        # shrink it, or M and cap co-vary and the
                                        # curve confounds capacity with M

ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

USE_PARALLEL_PREFILL=True
THREAD_MEMORY=True

for LR in ${LRS:-1e-04}; do
  for N in ${RUNS:-1 2}; do
    for NUM_MEMORY_VECTORS in ${MS:-32 8 4}; do

      RUN_NAME="rmmv6p6_${WRITE_MODE}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}"
      RUN_NAME="${RUN_NAME}_cap${MAX_MEMORY_VECTORS}_M${NUM_MEMORY_VECTORS}_lr${LR}_bs${TBS}_tps${TOKENS_PER_SEGMENT}_id_init"
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
        --num_memory_vectors          $NUM_MEMORY_VECTORS \
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
    done
  done
done

echo "ratio_1seg worker done (RUNS='${RUNS:-1 2}' MS='${MS:-32 8 4}' LRS='${LRS:-1e-04}')"
