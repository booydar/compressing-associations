#!/bin/bash
set -e

# Resume v5p4 training from a previously-saved checkpoint (full state:
# model + optimizer + scheduler + RNG + callbacks + step counter).
#
# Pass either:
#   - an explicit checkpoint-XXXX directory, or
#   - `latest` / `True` to let HF Trainer pick the newest checkpoint-* in EXP_PATH.
#
# Usage:
#   bash scripts/assoc-comp-rmm/run_rmm_v5p4_on_kv_retrieval-pool-7tps-resume.sh
#   CHECKPOINT=runs-rmmv5p4/.../checkpoint-12500 bash scripts/assoc-comp-rmm/run_rmm_v5p4_on_kv_retrieval-pool-7tps-resume.sh

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
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
N_PAIRS=8
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500
LR=3e-04

# ── RMM v5p4 memory path ───────────────────────────────────────────────────
WRITE_MODE=pool
READ_MODE=unpool
USE_PARALLEL_PREFILL=True
NUM_MEMORY_VECTORS=2
STATE_SIZE=32
TOKENS_PER_SEGMENT=7
PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))
N=1

RUN_NAME="rmmv5p4_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

EXP_PATH="./runs-rmmv5p4/${DATA_PATH}/${RUN_NAME}/run_${N}"

# Auto-detect latest checkpoint if CHECKPOINT not provided.
CHECKPOINT=${CHECKPOINT:-latest}

if [ ! -d "$EXP_PATH" ]; then
  echo "EXP_PATH does not exist: $EXP_PATH"
  echo "Run the base script first to produce checkpoints, or set EXP_PATH explicitly."
  exit 1
fi

echo "Resuming: $EXP_PATH   (checkpoint=$CHECKPOINT)"
accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmm_on_kv_retrieval-v5p4.py \
  --exp_path                    "$EXP_PATH" \
  --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
  --gradient_accumulation_steps $GRAD_ACC_STEPS \
  --total_batch_size            $TBS \
  --data_path                   "./data/${DATA_PATH}" \
  --tokenizer_path              "$TOKENIZER_PATH" \
  --base_model                  $BASE_MODEL \
  --n_layer                     $L \
  --n_head                      $H \
  --n_embd                      $D \
  --fla_layer                   $FLA_LAYER \
  --state_size                  $STATE_SIZE \
  --expand_v                    $EXPAND_V \
  --conv_kernel                 $CONV_KERNEL \
  --num_memory_vectors          $NUM_MEMORY_VECTORS \
  --write_mode                  $WRITE_MODE \
  --read_mode                   $READ_MODE \
  --use_parallel_prefill        $USE_PARALLEL_PREFILL \
  --tokens_per_segment          $TOKENS_PER_SEGMENT \
  --n_pairs                     $N_PAIRS \
  --n_keys                      $K \
  --n_values                    $V \
  --learning_rate               $LR \
  --max_steps                   $ITERS \
  --warmup_steps                $WARMUP \
  --eval_steps                  $EVAL_STEPS \
  --logging_steps               $EVAL_STEPS \
  --early_stopping_patience     $EARLY_STOP \
  --seed                        $((142 + N)) \
  --checkpoint                  "$CHECKPOINT"

echo "Done"
