#!/bin/bash
set -e
# Reproduce the RMT bAbI runs with RMM v6p0.
# RMM analog of example-scripts/babi/run_rmt_on_babi.sh: small from-config gpt2
# base (--base_model gpt2), babilong qa1..qa5, LR sweep, 200k steps.
#
# Prereq: bash scripts/download_babi.sh   (downloads ./data/babilong_qaX_0k)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Single GPU: >1 visible GPU makes HF Trainer wrap the model in nn.DataParallel,
# which trips parallel_forward's next(self.model.parameters()) StopIteration.
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# base model (small from-config gpt2, as RMT babi)
BASE_MODEL=gpt2
PRETRAINED_MODEL=gpt2   # tokenizer
L=4; H=1; D=128
# GDN / RMM v6p0 memory path
FLA_LAYER=GatedDeltaNet
STATE_SIZE=32; EXPAND_V=2.0; CONV_KERNEL=4
NUM_MEMORY_VECTORS=8
WRITE_MODE=identity
READ_MODE=identity
MAX_CONTEXT_LENGTH=1024

N=1
for LR in 3e-04 ; do
  # for task_name in "qa1"; do
  for task_name in "qa1" "qa2" "qa3" "qa4" "qa5"; do
  # for task_name in "qa2" "qa1"; do
    DATA_NAME="babilong_${task_name}_0k"
    DATA_PATH="./data/${DATA_NAME}"
    RUN_NAME="rmmv6p0_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${WRITE_MODE}_${READ_MODE}_lr${LR}_bs${TBS}"
    EXP_PATH="./runs-rmmv6p0/babi/${DATA_NAME}/${RUN_NAME}/run_${N}"
    if [ -d "$EXP_PATH" ]; then echo "exists, skip $EXP_PATH"; continue; fi

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
      --tokenizer_path              $PRETRAINED_MODEL \
      --base_model                  $BASE_MODEL \
      --n_layer $L --n_head $H --n_embd $D \
      --max_context_length          $MAX_CONTEXT_LENGTH \
      --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V --conv_kernel $CONV_KERNEL \
      --num_memory_vectors $NUM_MEMORY_VECTORS --write_mode $WRITE_MODE --read_mode $READ_MODE \
      --use_parallel_prefill True \
      --learning_rate $LR \
      --max_steps 80000 \
      --eval_steps 500 --logging_steps 500 --warmup_steps 10000 \
      --early_stopping_patience 500 \
      --seed $((142 + N))
  done
done
echo "Done"
