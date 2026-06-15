#!/bin/bash
set -e
# Reproduce the RMT short-SQuAD runs with RMM v6p0.
# RMM analog of example-scripts/squad-short/run_rmt_on_squad_short.sh: pretrained
# gpt2 base, mkairov/short_squad, M in {8,16,32}, 75k steps, seeds {2,3}.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

PRETRAINED_MODEL=gpt2          # full pretrained gpt2 base
DATASET_NAME="mkairov/short_squad"
LR=3e-04
LR_SCHEDULER_TYPE="constant_with_warmup"
# GDN / RMM v6p0 memory path
FLA_LAYER=GatedDeltaNet
STATE_SIZE=32; EXPAND_V=2.0; CONV_KERNEL=4
WRITE_MODE=pool
READ_MODE=unpool

for NUM_MEMORY_VECTORS in 8 16 32; do
  for LR in 1e-04 3e-04 1e-03; do
    for N in 1; do
      RUN_NAME="rmmv6p0_gpt2_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${WRITE_MODE}_${READ_MODE}_lr${LR}_bs${TBS}"
      EXP_PATH="./runs-rmmv6p0/squad-short/${RUN_NAME}/run_${N}"
      if [ -d "$EXP_PATH" ]; then echo "exists, skip $EXP_PATH"; continue; fi

      accelerate launch \
        --main_process_port 0 \
        --num_processes $NP \
        --mixed_precision bf16 \
        --config_file accelerate.yaml \
        run_rmm_on_squad-v6p0.py \
        --exp_path                    "$EXP_PATH" \
        --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
        --gradient_accumulation_steps $GRAD_ACC_STEPS \
        --total_batch_size            $TBS \
        --dataset_name                "$DATASET_NAME" \
        --pretrained_model            $PRETRAINED_MODEL \
        --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V --conv_kernel $CONV_KERNEL \
        --num_memory_vectors $NUM_MEMORY_VECTORS --write_mode $WRITE_MODE --read_mode $READ_MODE \
        --use_parallel_prefill True \
        --learning_rate $LR --lr_scheduler_type $LR_SCHEDULER_TYPE \
        --max_steps 75000 \
        --eval_steps 500 --logging_steps 500 --warmup_steps 10000 \
        --early_stopping_patience 500 \
        --seed $((142 + N))
    done
  done
done
echo "Done"
