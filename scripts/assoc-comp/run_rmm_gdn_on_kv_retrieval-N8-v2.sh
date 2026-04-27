#!/bin/bash
set -e

# Define arguments for the script
NP=${NP:-1}  # Default to 1 process if not set
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
ITERS=200000

BASE_MODEL=llama
N_LAYER=4
N_HEAD=1
N_EMBD=128
FLA_LAYER=GatedDeltaNet
EXPAND_V=2
CONV_KERNEL=4

K=2
V=2

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

N_SEGMENTS=1

for STATE_SIZE in 4 16 32; do
  for PAIRS_PER_SEGMENT in 8 16 32; do
    for LR in 3e-4 1e-4; do
      for N in 4 5 6; do

        N_PAIRS=$((N_SEGMENTS * PAIRS_PER_SEGMENT))
        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

        RUN_NAME="rmm_gdn_L${N_LAYER}H${N_HEAD}D${N_EMBD}_ss${STATE_SIZE}_ck${CONV_KERNEL}_lr${LR}-${PAIRS_PER_SEGMENT}pps-seed${N}"

        # Path to save experiment results
        EXP_PATH="./runs-rmm-gdn/${DATA_PATH}/${RUN_NAME}/run_$N"
        # if path exists, skip
        if [ -d "$EXP_PATH" ]; then
          echo "Path $EXP_PATH already exists, skipping"
          continue
        fi
        DATA_PATH_FULL="./data/${DATA_PATH}"

        # Execute the script using accelerate for parallel processing
        accelerate launch \
          --main_process_port 0 \
          --num_processes $NP \
          --mixed_precision bf16 \
          --config_file accelerate.yaml \
          run_rmm_on_kv_retrieval-v2.py \
          --exp_path $EXP_PATH \
          --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size $TBS \
          --data_path $DATA_PATH_FULL \
          --tokenizer_path $TOKENIZER_PATH \
          --learning_rate $LR \
          --n_layer $N_LAYER \
          --n_head $N_HEAD \
          --n_embd $N_EMBD \
          --n_pairs $N_PAIRS \
          --n_keys $K \
          --n_values $V \
          --base_model $BASE_MODEL \
          --fla_layer $FLA_LAYER \
          --state_size $STATE_SIZE \
          --expand_v $EXPAND_V \
          --conv_kernel $CONV_KERNEL \
          --pairs_per_segment $PAIRS_PER_SEGMENT \
          --max_steps $ITERS \
          --eval_steps 500 \
          --logging_steps 500 \
          --warmup_steps 10000 \
          --early_stopping_patience 500 \
          --seed $((142 + N))
      done
    done
  done
done

echo "Done"
