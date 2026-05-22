#!/bin/bash
set -e
# ARMT on Noisy-AR. tokens_per_segment = (1+K)*B: each model segment holds
# one KV pair worth + K noise blocks worth of chars. With VARY=1 (variable
# noise) the trainer's collator pads each sample to max-segments-in-batch.
# Datasets must be built: bash 00_build_data.sh
export HF_Trainer=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

NP=${NP:-1}
TBS=64; PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4; H=4; D=128
BASE_MODEL=llama
D_MEM=32; N_CTRL_TOKENS=0

K=2; V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

ITERS=${ITERS:-200000}; WARMUP=${WARMUP:-10000}
EVAL_STEPS=${EVAL_STEPS:-500}; EARLY_STOP=${EARLY_STOP:-500}

SEEDS="1 2"
N_PAIRS_LIST="4 8"
K_LIST="1"                 # noise blocks per pair
B=7                             # chars per noise block
VARY=1
VARY_TAG="-vary"

for N_PAIRS in $N_PAIRS_LIST; do
  for KK in $K_LIST; do
    TOKENS_PER_SEGMENT=7

    for N_MEM_TOKENS in 4 8; do
      for LR in 3e-04 1e-04; do
        for N in $SEEDS; do
          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_K${KK}${VARY_TAG}-B${B}_1M"
          if [ ! -d "./data/${DATA_PATH}" ]; then
            echo "missing: ./data/${DATA_PATH} — run 00_build_data.sh first"; continue
          fi

          RUN_NAME="armt_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}d${D_MEM}_lr${LR}_tps${TOKENS_PER_SEGMENT}_bs${TBS}"
          EXP_PATH="./runs-noisy-ar/${DATA_PATH}/${RUN_NAME}/run_${N}"
          [ -d "$EXP_PATH" ] && { echo "Skipping existing: $EXP_PATH"; continue; }

          echo "Launching: $EXP_PATH"
          accelerate launch \
            --main_process_port 0 --num_processes $NP \
            --mixed_precision bf16 --config_file accelerate.yaml \
            run_original_armt_on_kv_retrieval-v3-gen.py \
            --exp_path "$EXP_PATH" \
            --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
            --gradient_accumulation_steps $GRAD_ACC_STEPS \
            --total_batch_size $TBS \
            --data_path "./data/${DATA_PATH}" \
            --tokenizer_path "$TOKENIZER_PATH" \
            --learning_rate $LR \
            --n_layer $L --n_head $H --n_embd $D \
            --n_pairs $N_PAIRS --n_keys $K --n_values $V \
            --base_model $BASE_MODEL \
            --n_mem_tokens $N_MEM_TOKENS --n_ctrl_tokens $N_CTRL_TOKENS \
            --d_mem $D_MEM \
            --tokens_per_segment $TOKENS_PER_SEGMENT \
            --max_steps $ITERS --warmup_steps $WARMUP \
            --eval_steps $EVAL_STEPS --logging_steps $EVAL_STEPS \
            --early_stopping_patience $EARLY_STOP \
            --seed $((142 + N))
        done
      done
    done
  done
done
echo "Done"
