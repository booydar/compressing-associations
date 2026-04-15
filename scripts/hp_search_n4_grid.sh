#!/bin/bash
set -e

NP=${NP:-1}
TBS=2
PER_DEVICE_BATCH_SIZE=2
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
MAX_STEPS=50000
EVAL_STEPS=500
LOGGING_STEPS=500
WARMUP_STEPS=5000
L=4
H=4
BASE_MODEL=llama

K=4
V=4

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

N_CTRL_TOKENS=0
N_SEGMENTS=1
PAIRS_PER_SEGMENT=4
N_PAIRS=$((N_SEGMENTS * PAIRS_PER_SEGMENT))
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# Hyperparameter grid configurations
declare -a LRS=(5e-5 1e-4 3e-4 5e-4 1e-3)
declare -a EMBDS=(64 128 256)
declare -a MEM_TOKENS=(8 16 32)

RUN_ID=0

run_experiment() {
    local lr=$1
    local embd=$2
    local mem_tokens=$3
    
    RUN_NAME=hpsearch_n4_L${L}H${H}_mem${mem_tokens}_lr${lr}_embd${embd}_wd0.01_cosine_wup5000
    RUN_PATH="${RUN_NAME}/run_${RUN_ID}"
    
    EXP_PATH="./runs-hpsearch/${DATA_PATH}/${RUN_PATH}"
    DATA_DIR="./data/${DATA_PATH}"
    
    if [ -d "$EXP_PATH" ]; then
        echo "Skipping $RUN_NAME (already exists)"
        return
    fi
    
    # Use BS=1 with grad_acc to simulate effective batch size
    local bs=1
    local grad_acc=$TBS
    
    echo ""
    echo "=========================================="
    echo "Run $RUN_ID: $RUN_NAME"
    echo "LR=$lr, Embd=$embd, MemTokens=$mem_tokens, WD=0.01, Scheduler=cosine, Warmup=5000"
    echo "=========================================="
    
    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmca_on_kv_retrieval-v3.py \
      --exp_path $EXP_PATH \
      --per_device_batch_size $bs \
      --gradient_accumulation_steps $grad_acc \
      --total_batch_size $TBS \
      --data_path $DATA_DIR \
      --tokenizer_path $TOKENIZER_PATH \
      --learning_rate $lr \
      --n_layer $L \
      --n_head $H \
      --n_embd $embd \
      --n_pairs $N_PAIRS \
      --n_keys $K \
      --n_values $V \
      --base_model $BASE_MODEL \
      --n_mem_tokens $mem_tokens \
      --n_ctrl_tokens $N_CTRL_TOKENS \
      --pairs_per_segment $PAIRS_PER_SEGMENT \
      --max_steps $MAX_STEPS \
      --eval_steps $EVAL_STEPS \
      --logging_steps $LOGGING_STEPS \
      --warmup_steps $WARMUP_STEPS \
      --early_stopping_patience 20 \
      --weight_decay 0.01 \
      --lr_scheduler_type cosine \
      --seed $((42 + RUN_ID))
    
    ((RUN_ID++))
}

echo "Starting hyperparameter search for N4 task"
echo "Grid: LR=${#LRS[@]} × Embd=${#EMBDS[@]} × MemTokens=${#MEM_TOKENS[@]}"
echo "Total configurations: $((${#LRS[@]} * ${#EMBDS[@]} * ${#MEM_TOKENS[@]}))"
echo ""

# Full grid search: LR × Embedding × Memory Tokens
for lr in "${LRS[@]}"; do
    for embd in "${EMBDS[@]}"; do
        for mem_tokens in "${MEM_TOKENS[@]}"; do
            run_experiment $lr $embd $mem_tokens
        done
    done
done

echo ""
echo "=========================================="
echo "All experiments completed!"
echo "Total runs: $RUN_ID"
echo "Results saved in: ./runs-hpsearch/${DATA_PATH}/"
echo "=========================================="
