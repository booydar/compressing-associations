#!/bin/bash
set -e

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
ITERS=200000
L=4
H=1
D=128
BASE_MODEL=llama

K=2
V=2

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

N_SEGMENTS=1
FLA_LAYER=GatedDeltaNet

for PAIRS_PER_SEGMENT in 8 16; do
  for STATE_SIZE in 4 16 32; do
    for LR in 3e-04 1e-04; do
      for N in 1 2 3; do

        N_PAIRS=$((N_SEGMENTS * PAIRS_PER_SEGMENT))
        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

        RUN_NAME=rmm_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_lr${LR}-${N_SEGMENTS}x${PAIRS_PER_SEGMENT}

        RUN_NAME=${RUN_NAME}_bs_${TBS}_lr_${LR}-gen

        EXP_PATH="./runs-rmm/${DATA_PATH}/${RUN_NAME}/run_$N"
        if [ -d "$EXP_PATH" ]; then
          echo "Path $EXP_PATH already exists, skipping"
          continue
        fi
        DATA_PATH="./data/${DATA_PATH}"

        accelerate launch \
          --main_process_port 0 \
          --num_processes $NP \
          --mixed_precision bf16 \
          --config_file accelerate.yaml \
          run_rmm_on_kv_retrieval.py \
          --exp_path $EXP_PATH \
          --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size $TBS \
          --data_path $DATA_PATH \
          --tokenizer_path $TOKENIZER_PATH \
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
          --conv_kernel 4 \
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
