#!/bin/bash
set -e
# GDN baseline on Noisy-AR. Sweeps N×K×LR×seeds.
# Datasets must be built: bash 00_build_data.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

NP=${NP:-1}
TBS=64; PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4; H=4; D=128
BASE_MODEL=gated_delta_net
STATE_SIZE=32; CONV_KERNEL=4

K=2; V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

ITERS=200000; WARMUP=10000; EVAL_STEPS=500; EARLY_STOP=500

SEEDS="1 2"
N_PAIRS_LIST="4 8"
K_LIST="1"                 # noise blocks per pair
B=7                             # chars per noise block
VARY=1
VARY_TAG="-vary"

for N_PAIRS in $N_PAIRS_LIST; do
  for KK in $K_LIST; do
    for LR in 1e-03 3e-04; do
      for N in $SEEDS; do
        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_K${KK}${VARY_TAG}-B${B}_1M"
        if [ ! -d "./data/${DATA_PATH}" ]; then
          echo "missing: ./data/${DATA_PATH} — run 00_build_data.sh first"; continue
        fi

        RUN_NAME="gdn_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_ck${CONV_KERNEL}_lr${LR}_bs${TBS}"
        EXP_PATH="./runs-noisy-ar/${DATA_PATH}/${RUN_NAME}/run_${N}"
        [ -d "$EXP_PATH" ] && { echo "Skipping existing: $EXP_PATH"; continue; }

        echo "Launching: $EXP_PATH"
        accelerate launch \
          --main_process_port 0 --num_processes $NP \
          --mixed_precision bf16 --config_file accelerate.yaml \
          run_fla_on_kv_retrieval-default.py \
          --exp_path "$EXP_PATH" \
          --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size $TBS \
          --data_path "./data/${DATA_PATH}" \
          --tokenizer_path "$TOKENIZER_PATH" \
          --base_model $BASE_MODEL \
          --n_layer $L --n_head $H --n_embd $D \
          --state_size $STATE_SIZE --conv_kernel $CONV_KERNEL \
          --n_pairs $N_PAIRS --n_keys $K --n_values $V \
          --learning_rate $LR \
          --max_steps $ITERS --warmup_steps $WARMUP \
          --eval_steps $EVAL_STEPS --logging_steps $EVAL_STEPS \
          --early_stopping_patience $EARLY_STOP \
          --seed $((142 + N))
      done
    done
  done
done
echo "Done"
