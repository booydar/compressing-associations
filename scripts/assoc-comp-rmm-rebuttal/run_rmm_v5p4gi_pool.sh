#!/bin/bash
set -u
# Compressed-RMM (pool write / unpool read) sweep with optional open-gate init.
#
# Runs a queue of cells sequentially. A cell is a colon-separated tuple:
#   N_PAIRS:TPS:M:LR:GATE:RUN
# e.g. 16:7:8:1e-04:none:1   16:7:32:1e-04:both:1
# GATE is none|beta|decay|both. RUN n maps to seed 142+n (repo convention).
#
# Usage:  CELLS="16:7:8:1e-04:none:1 16:7:8:1e-04:both:1" ./run_rmm_v5p4gi_pool.sh
# Env:    ITERS (default 100000), TAG (exp-root subdir), DRY=1 to print only.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

PY=${PY:-$HOME/envs/mamba2/bin}

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model ──────────────────────────────────────────────────────────────────
L=4
H=${H:-1}          # H=1/head_dim=32 -> state-matched to the GDN baseline row
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=${STATE_SIZE:-32}

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-100000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=${EARLY_STOP:-120}     # 120 evals = 60k steps flat before a run is cut

# ── RMM memory path ────────────────────────────────────────────────────────
WRITE_MODE=pool
READ_MODE=unpool
USE_PARALLEL_PREFILL=True

TAG=${TAG:-rmmv5p4gi}

for CELL in ${CELLS:-}; do
  IFS=':' read -r N_PAIRS TOKENS_PER_SEGMENT NUM_MEMORY_VECTORS LR GATE RUN <<< "$CELL"
  PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))
  DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

  RUN_NAME="rmmv5p4gi_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
  RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
  RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}_gi${GATE}"

  EXP_PATH="./runs-rebuttal/${TAG}/${DATA_PATH}/${RUN_NAME}/run_${RUN}"
  if [ -d "$EXP_PATH" ]; then
    echo "[skip] exists: $EXP_PATH"
    continue
  fi

  echo "[launch] $EXP_PATH"
  [ "${DRY:-0}" = "1" ] && continue

  $PY/accelerate launch \
    --main_process_port 0 \
    --num_processes $NP \
    --mixed_precision bf16 \
    --config_file accelerate.yaml \
    run_rmm_on_kv_retrieval-v5p4gi.py \
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
    --gate_init                   $GATE \
    --seed                        $((142 + RUN))
  echo "[done] $EXP_PATH  rc=$?"
done
echo "queue drained"
