#!/bin/bash
export LIBRARY_PATH=/usr/local/cuda-11.4/targets/x86_64-linux/lib/stubs:$LIBRARY_PATH

NP=${NP:-1}
ADAM_BETA2=0.999
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))

N_HEAD=4
K=2
N_VALUES=(1 2 3)
LR_VALUES=(1e-03 3e-04)

VOCAB_SIZE=62
TOKENIZER_PATH="./tokenizers/kv_alphabet_${VOCAB_SIZE}/"

BASE_MODELS=(mamba)

N_LAYER=4
N_EMBD=128
# STATE_SIZE=16
STATE_SIZE=32

for LR in "${LR_VALUES[@]}"; do
  for BASE_MODEL in "${BASE_MODELS[@]}"; do
    for N_PAIRS in 2 4 8 16 32 64; do
      DATA_NAME="N${N_PAIRS}-K${K}V${K}-V${VOCAB_SIZE}_1M"
      DATA_PATH="./data/ar/${DATA_NAME}"

      for N in "${N_VALUES[@]}"; do
        RUN_NAME="${BASE_MODEL}_L${N_LAYER}D${N_EMBD}_ss${STATE_SIZE}_noconv"
        RUN_NAME=${RUN_NAME}_bs_${TBS}_lr_${LR}

        if [ -n "$ADAM_BETA2" ]; then
          RUN_NAME=${RUN_NAME}_b2_${ADAM_BETA2}
        fi

        EXP_PATH="./runs-rebuttal-default/${DATA_NAME}/${RUN_NAME}/run_${N}"
        if [ -d "$EXP_PATH" ]; then
          echo "Experiment path already exists: $EXP_PATH"
          continue
        fi

        accelerate launch \
          --main_process_port $((29500 + TBS + N + 1)) \
          --num_processes $NP \
          --mixed_precision bf16 \
          --config_file accelerate.yaml \
          run_fla_on_kv_retrieval-noconv.py \
          --exp_path $EXP_PATH \
          --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size $TBS \
          --data_path $DATA_PATH \
          --tokenizer_path $TOKENIZER_PATH \
          --learning_rate $LR \
          $( [ -n "$ADAM_BETA2" ] && echo "--adam_beta2 $ADAM_BETA2" ) \
          --n_layer $N_LAYER \
          --n_head $N_HEAD \
          --n_embd $N_EMBD \
          --state_size $STATE_SIZE \
          --no_conv True \
          --n_pairs $N_PAIRS \
          --n_keys $K \
          --n_values $K \
          --base_model $BASE_MODEL \
          --max_steps 200000 \
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
