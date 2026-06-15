#!/bin/bash
set -e
# SMOKE: RMM v6p0 on bAbI qa1. A few dozen steps to confirm it trains (loss down,
# no crash) and the parallel-prefill path runs. Not a real run.
# Prereq: bash scripts/download_babi.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
PER_DEVICE_BATCH_SIZE=16
TBS=16
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

DATA_PATH="./data/babilong_qa1_0k"
EXP_PATH="./runs-rmmv6p0-smoke/babi/qa1"
rm -rf "$EXP_PATH"

accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmm_on_babi-v6p0.py \
  --exp_path                    "$EXP_PATH" \
  --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
  --gradient_accumulation_steps $GRAD_ACC_STEPS \
  --total_batch_size            $TBS \
  --data_path                   "$DATA_PATH" \
  --tokenizer_path              gpt2 \
  --base_model                  gpt2 \
  --n_layer 4 --n_head 1 --n_embd 128 \
  --max_context_length          512 \
  --fla_layer GatedDeltaNet --state_size 32 --expand_v 2.0 --conv_kernel 4 \
  --num_memory_vectors 8 --write_mode pool --read_mode unpool \
  --use_parallel_prefill True \
  --learning_rate 3e-04 \
  --max_steps 30 \
  --eval_steps 10 --logging_steps 5 --warmup_steps 5 \
  --early_stopping_patience 1000 \
  --seed 142
echo "Done"
