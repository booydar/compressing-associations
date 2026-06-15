#!/bin/bash
cd /home/bulatov/rmt/test-time/compressing-associations-gdn
# Define arguments for the script
NP=${NP:-1}  # Default to 1 process if not set
# LR=1e-04
# ADAM_BETA2=0.95
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
PRETRAINED_MODEL=gpt2
K=1

# Dataset parameters
# DATA_NAME="babilong_qa1_0k"
# DATA_PATH="./data/${DATA_NAME}"

LR=3e-04
for N_MEM_TOKENS in 8; do
  MODEL_NAME=rmt2segm_gpt2_mem${N_MEM_TOKENS}_K1
  RUN_NAME="${MODEL_NAME}"
  
  MAX_CONTEXT_LENGTH=$((1024 - 2*$N_MEM_TOKENS))

  RUN_NAME=${RUN_NAME}_bs_${TBS}_lr_${LR}
  if [ -n "$ADAM_BETA2" ]; then
    RUN_NAME=${RUN_NAME}_b2_${ADAM_BETA2}
  fi

  for task_name in "qa1" "qa2" "qa3" "qa4" "qa5"; do
  # for task_name in "qa1"; do
    DATA_NAME="babilong_${task_name}_0k"
    DATA_PATH="./data/${DATA_NAME}"

    # Run ID
    N_VALUES=(1)
    for N in "${N_VALUES[@]}"; do
      # Path to save experiment results
      EXP_PATH="./runs-rmmv6p0/babi/${DATA_NAME}/${RUN_NAME}/run_$N"
      if [ -d "$EXP_PATH" ]; then
        echo "Experiment path $EXP_PATH already exists. Skipping..."
        continue
      fi

      # Execute the script using accelerate for parallel processing
      accelerate launch \
        --main_process_port $((29500+100*$K+$TBS+$N+920)) \
        --num_processes $NP \
        --mixed_precision bf16 \
        --config_file accelerate.yaml \
        run_rmt_on_kv_retrieval.py \
        --exp_path $EXP_PATH \
        --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
        --gradient_accumulation_steps $GRAD_ACC_STEPS \
        --total_batch_size $TBS \
        --data_path $DATA_PATH \
        --learning_rate $LR \
        --pretrained_model $PRETRAINED_MODEL \
        --n_mem_tokens $N_MEM_TOKENS \
        --K $K \
        --tokenizer_path $PRETRAINED_MODEL \
        --max_context_length $MAX_CONTEXT_LENGTH \
        $( [ -n "$ADAM_BETA2" ] && echo "--adam_beta2 $ADAM_BETA2" ) \
        $( [ -n "$MAX_POSITION_EMBEDDINGS" ] && echo "--max_position_embeddings $MAX_POSITION_EMBEDDINGS" ) \
        --max_steps 100000 \
        --eval_steps 500 \
        --logging_steps 250 \
        --warmup_steps 1000 \
        --early_stopping_patience 500 \
        --seed $((142+$N))
    done
  done
done
echo "Done"
