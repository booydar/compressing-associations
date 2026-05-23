#!/bin/bash
set -e
export CUDA_VISIBLE_DEVICES=1
# ARMT baseline for the v5p1 7tps main experiment.
# Mirrors run_original_rmt_on_kv_retrieval-7tps-baseline.sh: same dataset,
# collator, and segmentation (1 pair per segment, configurable via
# PAIRS_PER_SEGMENT). Capacity sweep over n_mem_tokens to compare against
# RMM v5p1 M ∈ {1,2,4}.
export HF_Trainer=true
export WANDB_PROJECT=${WANDB_PROJECT:-compressing-associations}
export WANDB_WATCH=${WANDB_WATCH:-false}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model ──────────────────────────────────────────────────────────────────
L=4
H=4
D=128
BASE_MODEL=llama

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── ARMT specifics ─────────────────────────────────────────────────────────
N_CTRL_TOKENS=0
USE_MEM_PROJ=false
MEM_PROJ_MODE="proj"
D_MEM=21

# ── segmentation: 1 pair per segment to mirror v5p1 tps=7 ──────────────────
N_PAIRS=8

# ── sweep ──────────────────────────────────────────────────────────────────
for PAIRS_PER_SEGMENT in 1; do
  for N_MEM_TOKENS in 4; do
    for LR in 3e-04 1e-04; do
      for N in 1; do

        N_SEGMENTS=$(( N_PAIRS / PAIRS_PER_SEGMENT ))
        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

        RUN_NAME=armt_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}d${D_MEM}_lr${LR}-${N_SEGMENTS}x${PAIRS_PER_SEGMENT}
        if [ "$N_CTRL_TOKENS" -gt 0 ]; then
          RUN_NAME=${RUN_NAME}_c${N_CTRL_TOKENS}
        fi
        if [ "$USE_MEM_PROJ" = true ]; then
          RUN_NAME=${RUN_NAME}_mem_proj
        fi
        RUN_NAME=${RUN_NAME}_bs${TBS}-gen

        EXP_PATH="./runs-baselines/${DATA_PATH}/${RUN_NAME}/run_${N}"
        # if [ -d "$EXP_PATH" ]; then
        #   echo "Skipping existing: $EXP_PATH"
        #   continue
        # fi

        echo "Launching: $EXP_PATH"
        accelerate launch \
          --main_process_port 0 \
          --num_processes $NP \
          --mixed_precision bf16 \
          --config_file accelerate.yaml \
          run_original_armt_on_kv_retrieval-v3-gen.py \
          --exp_path                    "$EXP_PATH" \
          --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size            $TBS \
          --data_path                   "./data/${DATA_PATH}" \
          --tokenizer_path              "$TOKENIZER_PATH" \
          --learning_rate               $LR \
          --n_layer                     $L \
          --n_head                      $H \
          --n_embd                      $D \
          --n_pairs                     $N_PAIRS \
          --n_keys                      $K \
          --n_values                    $V \
          --base_model                  $BASE_MODEL \
          --n_mem_tokens                $N_MEM_TOKENS \
          --n_ctrl_tokens               $N_CTRL_TOKENS \
          $( [ "$USE_MEM_PROJ" = true ] && echo "--use_mem_proj" ) \
          $( [ "$USE_MEM_PROJ" = true ] && echo "--mem_proj_mode $MEM_PROJ_MODE" ) \
          --d_mem                       $D_MEM \
          --pairs_per_segment           $PAIRS_PER_SEGMENT \
          --max_steps                   $ITERS \
          --eval_steps                  $EVAL_STEPS \
          --logging_steps               $EVAL_STEPS \
          --warmup_steps                $WARMUP \
          --early_stopping_patience     $EARLY_STOP \
          --report_to                   wandb \
          --run_name                    "$RUN_NAME/run_${N}" \
          --wandb_project               "$WANDB_PROJECT" \
          --seed                        $((142 + N))
      done
    done
  done
done

echo "Done"
