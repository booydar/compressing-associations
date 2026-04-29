#!/bin/bash
# Launch script for autoresearch experiments.
# Usage: bash scripts/run_autoresearch_exp.sh <EXP_PATH> <N_PAIRS> [MAX_STEPS]
#
# The Python training script is controlled by the MAIN_SCRIPT env var (set by
# autoresearch.py from config["main_script"]) so this wrapper stays agnostic.
# All model-specific hyperparameters arrive as env vars and are forwarded via
# their uppercase names; each script uses the ones it needs via ${VAR:-default}.
set -e

EXP_PATH=${1:?usage: run_autoresearch_exp.sh EXP_PATH N_PAIRS [MAX_STEPS]}
N_PAIRS=${2:?usage: run_autoresearch_exp.sh EXP_PATH N_PAIRS [MAX_STEPS]}
MAX_STEPS=${3:-25000}

MAIN_SCRIPT=${MAIN_SCRIPT:-run_rmm_on_kv_retrieval-v2.py}

NP=${NP:-1}
PER_DEVICE_BATCH_SIZE=${PER_DEVICE_BATCH_SIZE:-64}
TBS=$((PER_DEVICE_BATCH_SIZE * NP))
GRAD_ACC_STEPS=1

# Standard architecture / training knobs
L=${L:-4}
H=${H:-1}
D=${D:-128}
BASE_MODEL=${BASE_MODEL:-gpt2}
K=${K:-2}
V=${V:-2}
LR=${LR:-1e-4}
PAIRS_PER_SEGMENT=${PAIRS_PER_SEGMENT:-$N_PAIRS}
EVAL_STEPS=${EVAL_STEPS:-500}
LOGGING_STEPS=${LOGGING_STEPS:-500}
WARMUP_STEPS=${WARMUP_STEPS:-2000}
EARLY_STOPPING_PATIENCE=${EARLY_STOPPING_PATIENCE:-20}
SEED=${SEED:-142}

# RMM-specific knobs (ignored by scripts that don't accept them)
FLA_LAYER=${FLA_LAYER:-GatedDeltaNet}
STATE_SIZE=${STATE_SIZE:-32}
EXPAND_V=${EXPAND_V:-2.0}
CONV_KERNEL=${CONV_KERNEL:-4}

# Legacy RMCA knob — kept so RMCA scripts still work when MAIN_SCRIPT points to one
N_MEM_TOKENS=${N_MEM_TOKENS:-8}

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="./data/N${N_PAIRS}-K${K}V${V}-V62_1M"

echo "=== autoresearch experiment ==="
echo "SCRIPT:    $MAIN_SCRIPT"
echo "EXP_PATH:  $EXP_PATH"
echo "N_PAIRS:   $N_PAIRS  (K=$K, V=$V)"
echo "MAX_STEPS: $MAX_STEPS"
echo "BS:        $TBS  (per_device=$PER_DEVICE_BATCH_SIZE, NP=$NP)"
echo "MODEL:     L=$L H=$H D=$D  fla=$FLA_LAYER state=$STATE_SIZE"
echo "LR:        $LR"
echo "==============================="

accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  "$MAIN_SCRIPT" \
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
  --fla_layer $FLA_LAYER \
  --state_size $STATE_SIZE \
  --expand_v $EXPAND_V \
  --conv_kernel $CONV_KERNEL \
  --pairs_per_segment $PAIRS_PER_SEGMENT \
  --max_steps $MAX_STEPS \
  --eval_steps $EVAL_STEPS \
  --logging_steps $LOGGING_STEPS \
  --warmup_steps $WARMUP_STEPS \
  --early_stopping_patience $EARLY_STOPPING_PATIENCE \
  --seed $SEED

echo "=== experiment done: $EXP_PATH ==="
