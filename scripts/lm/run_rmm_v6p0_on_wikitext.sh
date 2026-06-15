#!/bin/bash
set -e
# Reproduce the RMT wikitext-LM run with RMM v6p0.
# RMM analog of example-scripts/lm/run_rmt_on_wikitext.sh: pretrained gpt2 base,
# wikitext-103, context 128 / segment 128, M=32, 200k steps.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
TBS=256
PER_DEVICE_BATCH_SIZE=128
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

PRETRAINED_MODEL=gpt2
LR=3e-04
CONTEXT_SIZE=128
SEGMENT_SIZE=128
# GDN / RMM v6p0 memory path
FLA_LAYER=GatedDeltaNet
STATE_SIZE=32; EXPAND_V=2.0; CONV_KERNEL=4
NUM_MEMORY_VECTORS=32
WRITE_MODE=pool
READ_MODE=unpool

N=1
RUN_NAME="rmmv6p0_gpt2_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${WRITE_MODE}_${READ_MODE}_lr${LR}_bs${TBS}_ctx${CONTEXT_SIZE}-${SEGMENT_SIZE}"
EXP_PATH="./runs-rmmv6p0/wikitext/${RUN_NAME}/run_${N}"

accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmm_on_lm-v6p0.py \
  --exp_path                    "$EXP_PATH" \
  --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
  --gradient_accumulation_steps $GRAD_ACC_STEPS \
  --total_batch_size            $TBS \
  --dataset_name                wikitext \
  --pretrained_model            $PRETRAINED_MODEL \
  --context_size $CONTEXT_SIZE --segment_size $SEGMENT_SIZE \
  --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V --conv_kernel $CONV_KERNEL \
  --num_memory_vectors $NUM_MEMORY_VECTORS --write_mode $WRITE_MODE --read_mode $READ_MODE \
  --use_parallel_prefill True \
  --learning_rate $LR --lr_scheduler_type constant_with_warmup \
  --max_steps 200000 \
  --eval_steps 1000 --logging_steps 100 --warmup_steps 10000 \
  --early_stopping_patience 500 \
  --seed $((142 + N))
echo "Done"
