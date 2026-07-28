#!/bin/bash
# Parameterized N16 token-level (identity/identity, tps7) SOURCE trainer.
#
# Purpose: produce warm-start source checkpoints for NEW seeds. The existing
# sources (runs-rebuttal/.../N16.../*tps7*/run_{1,2}) only cover seeds 143/144
# and were trained to ~143k steps. This script deliberately trains a SHORT
# source (default 30k) so that source+target compute stays BELOW the 200k
# from-scratch budget it is being compared against -- which removes the
# "warm start is not compute-matched" caveat on the N32 result.
#
# Writes into the runs-rebuttal tree with the exact naming the warm-start
# script expects, so run_rmm_v5p7_N32_warmstart_param.sh can find it.
#
# Env: SEED (default 145), LR (1e-04), ITERS (30000), CUDA_VISIBLE_DEVICES.
# RUN_IDX is derived as SEED-142, matching the repo convention (--seed 142+N).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# fla env holds the fla/GDN library + accelerate for v5p7 (see reference-remote-layout)
export PATH="$HOME/envs/fla/bin:$PATH"
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}

SEED=${SEED:-145}
RUN_IDX=$(( SEED - 142 ))
LR=${LR:-1e-04}
ITERS=${ITERS:-30000}
WARMUP=${WARMUP:-2000}
EVAL_STEPS=500
EARLY_STOP=500

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4; H=1; D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32
NUM_MEMORY_VECTORS=32

K=2; V=2; N_PAIRS=16
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True
TOKENS_PER_SEGMENT=7
PAIRS_PER_SEGMENT=1

RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"
EXP_PATH="./runs-rebuttal/rmmv5p7/${DATA_PATH}/${RUN_NAME}/run_${RUN_IDX}"

if [ -d "$EXP_PATH" ]; then
  echo "Skipping existing: $EXP_PATH"
  exit 0
fi

echo "=== [N16 src seed ${SEED}] Launching: $EXP_PATH (ITERS=$ITERS)"
accelerate launch \
  --main_process_port 0 --num_processes $NP --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmm_on_kv_retrieval-v5p7.py \
  --exp_path "$EXP_PATH" \
  --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
  --gradient_accumulation_steps $GRAD_ACC_STEPS \
  --total_batch_size $TBS \
  --data_path "./data/${DATA_PATH}" \
  --tokenizer_path "$TOKENIZER_PATH" \
  --base_model $BASE_MODEL --n_layer $L --n_head $H --n_embd $D \
  --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V \
  --conv_kernel $CONV_KERNEL --num_memory_vectors $NUM_MEMORY_VECTORS \
  --write_mode $WRITE_MODE --read_mode $READ_MODE \
  --use_parallel_prefill $USE_PARALLEL_PREFILL \
  --tokens_per_segment $TOKENS_PER_SEGMENT \
  --n_pairs $N_PAIRS --n_keys $K --n_values $V \
  --learning_rate $LR --max_steps $ITERS --warmup_steps $WARMUP \
  --eval_steps $EVAL_STEPS --logging_steps $EVAL_STEPS \
  --early_stopping_patience $EARLY_STOP --seed $SEED
echo "=== [N16 src seed ${SEED}] exit=$?"
