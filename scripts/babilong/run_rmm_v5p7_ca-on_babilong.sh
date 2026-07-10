#!/bin/bash
set -e
# RMM v5p7 (paper version; write=cross_attn, read=cross_attn) on babilong.
# Exact analog of babilong-release finetune_babilong_qa1_rmt_vary_n_seg.sh:
# pretrained gpt2 backbone, 16 memory vectors, segment 512, MAX_N_SEGMENTS=1,
# TBS 64 (BS = 64/MAX_N_SEGMENTS), AdamW lr 1e-05, linear scheduler, wd 0.01,
# ITERS 2000, warmup ITERS/10, eval ITERS/20, log ITERS/100, patience 15,
# optimize exact_match, seed N+42 (N=6), --vary_n_segments, clip 1.0 (HF default).
# Produces seg${MAX_N_SEGMENTS}_from0/model_best.pt; the -curriculum.sh script
# picks up the seg1 run as its first stage.
#
# Prereq: bash scripts/babilong/download_babilong_data.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Single GPU: >1 visible GPU makes HF Trainer wrap the model in nn.DataParallel,
# which trips parallel_forward's next(self.model.parameters()) StopIteration.
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}
TBS=64
INIT_BS=64

# backbone: pretrained gpt2, as the original babilong experiment
PRETRAINED_MODEL=gpt2
# GDN / RMM v5p7 memory path
FLA_LAYER=GatedDeltaNet
H=1                    # GDN heads; head_dim = STATE_SIZE / H
STATE_SIZE=32; EXPAND_V=2.0; CONV_KERNEL=4
WRITE_MODE=cross_attn
READ_MODE=cross_attn
NUM_MEMORY_VECTORS=16  # MEMORY_SIZE=16 in the original scripts
# babilong (original: SEGMENT_SIZE=512, MAX_N_SEGMENTS=1, ITERS=2000)
NOISE_DATASET=emozilla/pg19
SEGMENT_SIZE=512
MAX_N_SEGMENTS=${MAX_N_SEGMENTS:-1}
ITERS=${ITERS:-2000}
BS=$(( INIT_BS / MAX_N_SEGMENTS ))
GRAD_ACC_STEPS=$(( TBS / (BS * NP) ))

declare -A TASK_NAMES=(
  [qa1]=qa1_single-supporting-fact
  [qa2]=qa2_two-supporting-facts
  [qa3]=qa3_three-supporting-facts
  [qa4]=qa4_two-arg-relations
  [qa5]=qa5_three-arg-relations
)

N=6
for LR in 1e-05 ; do
  # for task in "qa1" "qa2" "qa3" "qa4" "qa5"; do
  for task in "qa1"; do
    TASK_DATASET=${TASK_NAMES[$task]}
    RUN_NAME="rmmv5p7_gpt2pre_ss${STATE_SIZE}_${WRITE_MODE}_${READ_MODE}_mem${NUM_MEMORY_VECTORS}_lr${LR}_bs${TBS}"
    EXP_PATH="./runs-rmmv5p7/babilong/${task}/${RUN_NAME}/seg${MAX_N_SEGMENTS}_from0/run_${N}"
    if [ -d "$EXP_PATH" ]; then echo "exists, skip $EXP_PATH"; continue; fi

    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmm_on_babilong-v5p7.py \
      --exp_path                    "$EXP_PATH" \
      --per_device_batch_size       $BS \
      --gradient_accumulation_steps $GRAD_ACC_STEPS \
      --total_batch_size            $TBS \
      --babi_path                   ./data/tasks_1-20_v1-2/en-10k \
      --task_dataset                $TASK_DATASET \
      --noise_dataset               $NOISE_DATASET \
      --segment_size                $SEGMENT_SIZE \
      --max_n_segments              $MAX_N_SEGMENTS \
      --vary_n_segments             True \
      --pretrained_model            $PRETRAINED_MODEL \
      --n_head $H \
      --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V --conv_kernel $CONV_KERNEL \
      --num_memory_vectors $NUM_MEMORY_VECTORS --write_mode $WRITE_MODE --read_mode $READ_MODE \
      --use_parallel_prefill True \
      --learning_rate $LR --lr_scheduler_type linear --weight_decay 0.01 \
      --max_steps $ITERS \
      --warmup_steps $(( ITERS / 10 )) \
      --eval_steps $(( ITERS / 20 )) --logging_steps $(( ITERS / 100 )) \
      --metric_for_best_model exact_match \
      --early_stopping_patience 15 \
      --seed $(( N + 42 ))
  done
done
echo "Done"
