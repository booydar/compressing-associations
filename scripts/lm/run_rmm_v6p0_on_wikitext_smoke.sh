#!/bin/bash
set -e
# SMOKE: RMM v6p0 on wikitext-103 LM with pretrained gpt2. Subsets the raw rows
# (--max_train_samples / --max_eval_samples) so tokenization+grouping is fast, then
# trains a few dozen steps to confirm loss decreases and valid/test eval runs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
PER_DEVICE_BATCH_SIZE=8
TBS=8
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

EXP_PATH="./runs-rmmv6p0-smoke/wikitext"
rm -rf "$EXP_PATH"

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
  --pretrained_model            gpt2 \
  --context_size 128 --segment_size 128 \
  --num_proc 8 \
  --max_train_samples 20000 --max_eval_samples 2000 \
  --fla_layer GatedDeltaNet --state_size 32 --expand_v 2.0 --conv_kernel 4 \
  --num_memory_vectors 32 --write_mode pool --read_mode unpool \
  --use_parallel_prefill True \
  --learning_rate 3e-04 \
  --max_steps 30 \
  --eval_steps 10 --logging_steps 5 --warmup_steps 5 \
  --early_stopping_patience 1000 \
  --seed 142
echo "Done"
