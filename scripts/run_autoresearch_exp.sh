#!/bin/bash
# Launch script for autoresearch experiments.
# Usage: bash scripts/run_autoresearch_exp.sh <EXP_PATH> <N_PAIRS> [MAX_STEPS]
# All other hyperparameters come from .autoresearch/config.yaml via autoresearch.py,
# which passes them as env vars before calling this script.
set -e

EXP_PATH=${1:?usage: run_autoresearch_exp.sh EXP_PATH N_PAIRS [MAX_STEPS]}
N_PAIRS=${2:?usage: run_autoresearch_exp.sh EXP_PATH N_PAIRS [MAX_STEPS]}
MAX_STEPS=${3:-5000}

NP=${NP:-1}
PER_DEVICE_BATCH_SIZE=${PER_DEVICE_BATCH_SIZE:-64}
TBS=$((PER_DEVICE_BATCH_SIZE * NP))
GRAD_ACC_STEPS=1

L=${L:-4}
H=${H:-4}
D=${D:-128}
BASE_MODEL=${BASE_MODEL:-llama}
K=${K:-2}
V=${V:-2}
N_MEM_TOKENS=${N_MEM_TOKENS:-8}
PAIRS_PER_SEGMENT=${PAIRS_PER_SEGMENT:-$N_PAIRS}
LR=${LR:-3e-4}
EVAL_STEPS=${EVAL_STEPS:-100}
LOGGING_STEPS=${LOGGING_STEPS:-50}
WARMUP_STEPS=${WARMUP_STEPS:-200}
EARLY_STOPPING_PATIENCE=${EARLY_STOPPING_PATIENCE:-20}
SEED=${SEED:-42}

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="./data/N${N_PAIRS}-K${K}V${V}-V62_1M"

echo "=== autoresearch experiment ==="
echo "EXP_PATH:  $EXP_PATH"
echo "N_PAIRS:   $N_PAIRS  (K=$K, V=$V)"
echo "MAX_STEPS: $MAX_STEPS"
echo "BS:        $TBS  (per_device=$PER_DEVICE_BATCH_SIZE, NP=$NP)"
echo "MODEL:     L=$L H=$H D=$D mem=$N_MEM_TOKENS"
echo "LR:        $LR"
echo "==============================="

accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmca_on_kv_retrieval-v3.py \
  --exp_path "$EXP_PATH" \
  --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
  --gradient_accumulation_steps $GRAD_ACC_STEPS \
  --total_batch_size $TBS \
  --data_path "$DATA_PATH" \
  --tokenizer_path "$TOKENIZER_PATH" \
  --learning_rate $LR \
  --n_layer $L \
  --n_head $H \
  --n_embd $D \
  --n_pairs $N_PAIRS \
  --n_keys $K \
  --n_values $V \
  --base_model $BASE_MODEL \
  --n_mem_tokens $N_MEM_TOKENS \
  --n_ctrl_tokens 0 \
  --pairs_per_segment $N_PAIRS \
  --max_steps $MAX_STEPS \
  --eval_steps $EVAL_STEPS \
  --logging_steps $LOGGING_STEPS \
  --warmup_steps $WARMUP_STEPS \
  --early_stopping_patience $EARLY_STOPPING_PATIENCE \
  --seed $SEED

echo "=== experiment done: $EXP_PATH ==="
