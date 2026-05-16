#!/bin/bash
set -e

# Full Transformer baseline (Llama) on KV retrieval.
# Anchors the "no recurrence" upper end of the brainstorm triplet:
#   full transformer  ↔  classical hybrid (sliding-window + GDN, TBD)  ↔  v5p1 hybrid.
# Same backbone budget as v5p1 sweep (L=4, H=4, D=128, bs=64).
# ~8 runs at 2 seeds.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model (locked) ─────────────────────────────────────────────────────────
L=4
H=4
D=128
BASE_MODEL=llama

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
VOCAB_SIZE=62
TOKENIZER_PATH="./tokenizers/kv_alphabet_${VOCAB_SIZE}/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=25000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=20

SEEDS=${SEEDS:-"1 2"}

# ── sweep ──────────────────────────────────────────────────────────────────
for N_PAIRS in 4 8; do
  for LR in 3e-04 1e-04; do
    for N in $SEEDS; do
      DATA_NAME="N${N_PAIRS}-K${K}V${V}-V${VOCAB_SIZE}_1M"
      if [ -d "./data/ar/${DATA_NAME}" ]; then
        DATA_PATH="./data/ar/${DATA_NAME}"
      else
        DATA_PATH="./data/${DATA_NAME}"
      fi

      RUN_NAME="${BASE_MODEL}_L${L}H${H}D${D}_lr${LR}_bs${TBS}"
      EXP_PATH="./runs-baselines-transformer/${DATA_NAME}/${RUN_NAME}/run_${N}"
      if [ -d "$EXP_PATH" ]; then
        echo "Skipping existing: $EXP_PATH"
        continue
      fi

      echo "Launching: $EXP_PATH"
      /cephfs/home/bulatov/envs/fla/bin/accelerate launch \
        --main_process_port 0 \
        --num_processes $NP \
        --mixed_precision bf16 \
        --config_file accelerate.yaml \
        run_gpt2_on_kv_retrieval.py \
        --exp_path                    "$EXP_PATH" \
        --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
        --gradient_accumulation_steps $GRAD_ACC_STEPS \
        --total_batch_size            $TBS \
        --data_path                   "$DATA_PATH" \
        --tokenizer_path              "$TOKENIZER_PATH" \
        --learning_rate               $LR \
        --base_model                  $BASE_MODEL \
        --n_layer                     $L \
        --n_head                      $H \
        --n_embd                      $D \
        --max_steps                   $ITERS \
        --eval_steps                  $EVAL_STEPS \
        --logging_steps               $EVAL_STEPS \
        --warmup_steps                $WARMUP \
        --early_stopping_patience     $EARLY_STOP \
        --seed                        $((142 + N))
    done
  done
done

echo "Done"
