#!/bin/bash
set -e

HF_Trainer=true

# Define arguments for the script
NP=${NP:-1}  # Default to 1 process if not set
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))

L=4
H=4
D=128
BASE_MODEL=llama
N_MEM_TOKENS=8

V=62
for DATA_PATH in "N8-K2V2-V62_1M"; do
  TOKENIZER_PATH="./tokenizers/kv_alphabet_${V}/"

  # ARMT-GDN specific parameters
  N_CTRL_TOKENS=0
  USE_MEM_PROJ=false
  MEM_PROJ_MODE="proj"

  # GDN-specific parameters
  USE_GDN_FORGET_GATE=true
  USE_DENOM=true
  CORRECTION=true
  ACT_ON=false
  MAX_HOP=4
  ACT_TYPE="layer"
  CONSTANT_DEPTH=false

  for LR in 3e-04; do
    for N in 1; do
      RUN_NAME=armt_gdn_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}_lr${LR}
      if [ "$USE_GDN_FORGET_GATE" = true ]; then
        RUN_NAME=${RUN_NAME}_gdn_fg
      fi
      if [ "$USE_DENOM" = true ]; then
        RUN_NAME=${RUN_NAME}_denom
      fi
      if [ "$ACT_ON" = true ]; then
        RUN_NAME=${RUN_NAME}_act${ACT_TYPE}_${MAX_HOP}
      fi
      if [ "$N_CTRL_TOKENS" -gt 0 ]; then
        RUN_NAME=${RUN_NAME}_c${N_CTRL_TOKENS}
      fi
      if [ "$USE_MEM_PROJ" = true ]; then
        RUN_NAME=${RUN_NAME}_mem_proj
      fi

      RUN_NAME=${RUN_NAME}_bs_${TBS}_lr_${LR}

      # Path to save experiment results
      EXP_PATH="./runs/test-time/${DATA_PATH}/${RUN_NAME}/run_$N"

      # Execute the script using accelerate for parallel processing
      accelerate launch \
        --main_process_port $((29500+$TBS+$N+1)) \
        --num_processes $NP \
        --mixed_precision bf16 \
        --config_file accelerate.yaml \
        run_original_armt_gdn_on_kv_retrieval.py \
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
        --base_model $BASE_MODEL \
        --n_mem_tokens $N_MEM_TOKENS \
        --n_heads_mem 1 \
        --d_mem 128 \
        --use_gdn_forget_gate $USE_GDN_FORGET_GATE \
        --use_denom $USE_DENOM \
        --correction $CORRECTION \
        --act_on $ACT_ON \
        --max_hop $MAX_HOP \
        --act_type $ACT_TYPE \
        --constant_depth $CONSTANT_DEPTH \
        --max_steps 100000 \
        --eval_steps 500 \
        --logging_steps 500 \
        --warmup_steps 10000 \
        --early_stopping_patience 500 \
        --seed $((142 + N))
    done
  done
done

echo "Done"
