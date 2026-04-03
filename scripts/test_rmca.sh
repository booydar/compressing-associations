#!/bin/bash
set -e

NP=${NP:-1}
TBS=1
PER_DEVICE_BATCH_SIZE=1
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
ITERS=10
L=2
H=2
D=64
BASE_MODEL=llama

K=2
V=2

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

N_CTRL_TOKENS=0
USE_MEM_PROJ=false
MEM_PROJ_MODE="proj"

N_SEGMENTS=1
PAIRS_PER_SEGMENT=8
N_MEM_TOKENS=8
LR=3e-04
N=4

N_PAIRS=$((N_SEGMENTS * PAIRS_PER_SEGMENT))
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

RUN_NAME=test_rmca_quick_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}
EXP_PATH="./runs-test/${DATA_PATH}/${RUN_NAME}/run_$N"
DATA_PATH="./data/${DATA_PATH}"

echo "Running quick RMCA test..."
echo "EXP_PATH: $EXP_PATH"
echo "NP=$NP, BS=$PER_DEVICE_BATCH_SIZE, STEPS=$ITERS"

accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmca_on_kv_retrieval-v2.py \
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
  --n_mem_tokens $N_MEM_TOKENS \
  --n_ctrl_tokens $N_CTRL_TOKENS \
  --pairs_per_segment $PAIRS_PER_SEGMENT \
  --max_steps $ITERS \
  --eval_steps 5 \
  --logging_steps 1 \
  --warmup_steps 2 \
  --early_stopping_patience 3 \
  --seed 42

echo "Done"
