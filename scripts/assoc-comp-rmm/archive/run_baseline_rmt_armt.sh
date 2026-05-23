#!/bin/bash
set -e

# Segment-level recurrent baselines (RMT, ARMT) — capacity sweep for RD §3.1.
# Mirrors v5p1 sweep ladder (N ∈ {4, 8}, L=4, H=4, D=128, bs=64) so M (v5p1)
# and n_mem_tokens (RMT/ARMT) sit on the same capacity axis: effective state
# is roughly n_mem_tokens × D.
# 1 pair per segment to match v5p1's pool-1tps regime in spirit.
# ~48 runs at 2 seeds (24 RMT + 24 ARMT).
export HF_Trainer=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model (locked to v5p1 ladder) ──────────────────────────────────────────
L=4
H=4
D=128
BASE_MODEL=llama

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=25000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=20

# ── segmentation: 1 pair per segment ───────────────────────────────────────
PAIRS_PER_SEGMENT=1

# ── ARMT specifics ─────────────────────────────────────────────────────────
N_CTRL_TOKENS=0
D_MEM=32

SEEDS=${SEEDS:-"1 2"}
# family ↔ runner mapping
declare -A RUNNER=(
  [rmt]="run_original_rmt_on_kv_retrieval-v3-gen.py"
  [armt]="run_original_armt_on_kv_retrieval-v3-gen.py"
)

# ── sweep ──────────────────────────────────────────────────────────────────
for FAMILY in rmt armt; do
  for N_PAIRS in 4 8; do
    for N_MEM_TOKENS in 1 4 16; do
      for LR in 3e-04 1e-04; do
        for N in $SEEDS; do

          N_SEGMENTS=$(( N_PAIRS / PAIRS_PER_SEGMENT ))
          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

          RUN_NAME="${FAMILY}_${BASE_MODEL}_L${L}H${H}D${D}_mem${N_MEM_TOKENS}"
          if [ "$FAMILY" = "armt" ]; then
            RUN_NAME="${RUN_NAME}d${D_MEM}"
          fi
          RUN_NAME="${RUN_NAME}_lr${LR}-${N_SEGMENTS}x${PAIRS_PER_SEGMENT}_bs${TBS}"

          EXP_PATH="./runs-baselines-segment/${DATA_PATH}/${RUN_NAME}/run_${N}"
          if [ -d "$EXP_PATH" ]; then
            echo "Skipping existing: $EXP_PATH"
            continue
          fi

          echo "Launching: $EXP_PATH"
          EXTRA_ARGS=()
          if [ "$FAMILY" = "armt" ]; then
            EXTRA_ARGS+=(--d_mem "$D_MEM")
          fi

          accelerate launch \
            --main_process_port 0 \
            --num_processes $NP \
            --mixed_precision bf16 \
            --config_file accelerate.yaml \
            "${RUNNER[$FAMILY]}" \
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
            --pairs_per_segment           $PAIRS_PER_SEGMENT \
            --max_steps                   $ITERS \
            --eval_steps                  $EVAL_STEPS \
            --logging_steps               $EVAL_STEPS \
            --warmup_steps                $WARMUP \
            --early_stopping_patience     $EARLY_STOP \
            "${EXTRA_ARGS[@]}" \
            --seed                        $((142 + N))
        done
      done
    done
  done
done

echo "Done"
