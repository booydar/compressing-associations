#!/bin/bash
set -e

NP=${NP:-1}
TBS=2
PER_DEVICE_BATCH_SIZE=2
GRAD_ACC_STEPS=$(($TBS/($PER_DEVICE_BATCH_SIZE*$NP)))
ITERS=100
L=2
H=2
D=64
BASE_MODEL=llama

K=2
V=2

TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

N_CTRL_TOKENS=0
USE_MEM_PROJ=false
MEM_PROJ_MODE="none"

N_SEGMENTS=1
PAIRS_PER_SEGMENT=2
N_MEM_TOKENS=8
N_PAIRS=$((N_SEGMENTS * PAIRS_PER_SEGMENT))
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# Hyperparameter grid configurations  
declare -a LRS=(1e-04 3e-04 5e-04 1e-03)
declare -a WDS=(0.0 0.01 0.1)
declare -a SCHEDULERS=("constant_with_warmup" "linear" "cosine")
declare -a WARMUPS=(10 20 50)

RUN_ID=0

run_experiment() {
    local lr=$1
    local eff_bs=$2
    local wd=$3
    local scheduler=$4
    local warmup=$5
    local suffix=$6
    
    RUN_NAME=hpsearch_n2_L${L}H${H}D${D}_mem${N_MEM_TOKENS}_lr${lr}_effbs${eff_bs}_wd${wd}_${scheduler}_wup${warmup}${suffix}
    
    EXP_PATH="./runs-hpsearch/${DATA_PATH}/${RUN_NAME}/run_${RUN_ID}"
    DATA_DIR="./data/${DATA_PATH}"
    
    if [ -d "$EXP_PATH" ]; then
        echo "Skipping $RUN_NAME (already exists)"
        return
    fi
    
    # Use BS=1 with grad_acc to simulate larger effective batch sizes
    local bs=1
    local grad_acc=$eff_bs
    
    echo ""
    echo "=========================================="
    echo "Run $RUN_ID: $RUN_NAME"
    echo "LR=$lr, EffBS=$eff_bs (BS=$bs, GA=$grad_acc), WD=$wd, Scheduler=$scheduler, Warmup=$warmup"
    echo "=========================================="
    
    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmca_on_kv_retrieval-v2.py \
      --exp_path $EXP_PATH \
      --per_device_batch_size $bs \
      --gradient_accumulation_steps $grad_acc \
      --total_batch_size $eff_bs \
      --data_path $DATA_DIR \
      --tokenizer_path $TOKENIZER_PATH \
      --learning_rate $lr \
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
      --eval_steps 10 \
      --logging_steps 5 \
      --warmup_steps $warmup \
      --early_stopping_patience 20 \
      --weight_decay $wd \
      --lr_scheduler_type $scheduler \
      --seed $((42 + RUN_ID))
    
    ((RUN_ID++))
}

echo "Starting hyperparameter search for N2 task"
echo "Total configurations: 16"
echo ""

# 1. LR sweep (4 runs) - EffBS=2, WD=0.0, constant, warmup=20
for lr in "${LRS[@]}"; do
    run_experiment $lr 2 0.0 "constant_with_warmup" 20 "_lrsweep"
done

# 2. Effective batch size sweep (3 runs) - LR=3e-04, WD=0.0, constant, warmup=20
run_experiment 3e-04 1 0.0 "constant_with_warmup" 20 "_bssweep1"
run_experiment 3e-04 2 0.0 "constant_with_warmup" 20 "_bssweep2"
run_experiment 3e-04 4 0.0 "constant_with_warmup" 20 "_bssweep4"

# 3. Weight decay sweep (2 runs) - EffBS=2, LR=3e-04, constant, warmup=20
for wd in 0.01 0.1; do
    run_experiment 3e-04 2 $wd "constant_with_warmup" 20 "_wdsweep"
done

# 4. Scheduler sweep (2 runs) - EffBS=2, LR=3e-04, WD=0.0, warmup=20
for sched in "linear" "cosine"; do
    run_experiment 3e-04 2 0.0 $sched 20 "_schesweep"
done

# 5. Warmup sweep (2 runs) - EffBS=2, LR=3e-04, WD=0.0, constant
for wup in 10 50; do
    run_experiment 3e-04 2 0.0 "constant_with_warmup" $wup "_wupsweep"
done

# 6. Combined promising configs (3 runs)
run_experiment 1e-04 4 0.01 "cosine" 50 "_combo1"
run_experiment 5e-04 2 0.01 "linear" 20 "_combo2"
run_experiment 3e-04 2 0.01 "cosine" 20 "_combo3"

# 7. Baseline (1 run) - original settings  
run_experiment 3e-04 1 0.0 "constant_with_warmup" 2 "_baseline"

echo ""
echo "=========================================="
echo "All experiments completed!"
echo "Total runs: $RUN_ID"
echo "Results saved in: ./runs-hpsearch/${DATA_PATH}/"
echo "=========================================="
