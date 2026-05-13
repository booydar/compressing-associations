#!/bin/bash
set -e

# ARMT baseline for the v5p1 7tps main experiment.
# Matches: N_PAIRS in {4, 2}, segmentation handled by ARMT (1 pair per segment),
# capacity sweep over n_mem_tokens to compare against RMM v5p1 M ∈ {1,2,4}.
# Reference: run_original_armt_on_kv_retrieval-1pps.sh; v5p1 sweep
# run_rmm_v5p1_on_kv_retrieval-pool-7tps.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

HF_Trainer=true

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
V_ALPHA=62
TOKENIZER_PATH="./tokenizers/kv_alphabet_${V_ALPHA}/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── ARMT specifics (legacy compat, unused) ─────────────────────────────────
N_CTRL_TOKENS=0
USE_MEM_PROJ=false
MEM_PROJ_MODE="proj"

# ── sweep ──────────────────────────────────────────────────────────────────
for N_PAIRS in 4 2; do
  for N_MEM_TOKENS in 1 2 4 8; do
    for LR in 3e-04 1e-04; do
      for N in 1 2; do

        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V${V_ALPHA}_1M"

        RUN_NAME=armt_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}_lr${LR}
        if [ "$N_CTRL_TOKENS" -gt 0 ]; then
          RUN_NAME=${RUN_NAME}_c${N_CTRL_TOKENS}
        fi
        if [ "$USE_MEM_PROJ" = true ]; then
          RUN_NAME=${RUN_NAME}_mem_proj
        fi
        RUN_NAME=${RUN_NAME}_bs${TBS}

        EXP_PATH="./runs-baselines/${DATA_PATH}/${RUN_NAME}/run_${N}"
        if [ -d "$EXP_PATH" ]; then
          echo "Skipping existing: $EXP_PATH"
          continue
        fi

        echo "Launching: $EXP_PATH"
        /cephfs/home/bulatov/envs/fla/bin/accelerate launch \
          --main_process_port $((29500 + TBS + N + 1)) \
          --num_processes $NP \
          --mixed_precision bf16 \
          --config_file accelerate.yaml \
          run_original_armt_on_kv_retrieval-v2.py \
          --exp_path                    "$EXP_PATH" \
          --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size            $TBS \
          --data_path                   "$DATA_PATH" \
          --tokenizer_path              "$TOKENIZER_PATH" \
          --learning_rate               $LR \
          --n_layer                     $L \
          --n_head                      $H \
          --n_embd                      $D \
          --base_model                  $BASE_MODEL \
          --n_mem_tokens                $N_MEM_TOKENS \
          --n_ctrl_tokens               $N_CTRL_TOKENS \
          $( [ "$USE_MEM_PROJ" = true ] && echo "--use_mem_proj" ) \
          $( [ "$USE_MEM_PROJ" = true ] && echo "--mem_proj_mode $MEM_PROJ_MODE" ) \
          --max_steps                   $ITERS \
          --eval_steps                  $EVAL_STEPS \
          --logging_steps               $EVAL_STEPS \
          --warmup_steps                $WARMUP \
          --early_stopping_patience     $EARLY_STOP \
          --seed                        $((142 + N))
      done
    done
  done
done

echo "Done"
