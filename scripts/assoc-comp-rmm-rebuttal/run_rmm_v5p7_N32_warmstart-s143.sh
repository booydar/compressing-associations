#!/bin/bash
# WORKER W2 — N32 token-level warm-start, seed 143 (CONTROL).
#
# Companion to run_rmm_v5p7_N32_warmstart-s144.sh. Seed 143 is the seed that
# already converges from scratch at N32 (97.8 tps224/lr5e-5, 87.7 tps7/lr1e-3).
# Warm-starting it is the control that says whether the warm-start helps, hurts,
# or is neutral for an already-healthy trajectory — without it, a seed-144
# rescue is uninterpretable (fix v3 "rescued" seed 144 while BREAKING seed 143,
# a role-reversal rather than a fix; see project_rmm_hybrid_vs_gdn_gap).
#
# Source: N16 tps7 identity, SAME seed, EM 0.990 (200k steps, converged).
#
# PASS = seed 143 stays converged (no regression). Together with W1, both seeds
# converging is the "GDN equivalence at N32" result.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}

# No `set -e`: queue worker, one failing cell must not kill the rest.

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model (identical to the N16 source checkpoint) ─────────────────────────
L=4
H=1
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32
NUM_MEMORY_VECTORS=32

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
N_PAIRS=32
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# ── memory path: the token-level endpoint ──────────────────────────────────
WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True
TOKENS_PER_SEGMENT=7          # 1 KV pair per segment
PAIRS_PER_SEGMENT=1

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-60000}
WARMUP=${WARMUP:-2000}
EVAL_STEPS=500
EARLY_STOP=500

SEED=143
RUN_IDX=1                     # matches seed 143 = 142 + 1
SRC_LR=1e-04                  # source checkpoint LR (N16 EM: 0.990)
SRC="./runs-rebuttal/rmmv5p7/N16-K2V2-V62_1M/rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}_lr${SRC_LR}_bs${TBS}_pps1_tps7/run_${RUN_IDX}"

if [ ! -d "$SRC" ]; then
  echo "FATAL: source checkpoint dir not found: $SRC"
  exit 1
fi
NCKPT=$(ls -d "$SRC"/checkpoint-* 2>/dev/null | wc -l)
if [ "$NCKPT" -ne 1 ]; then
  echo "FATAL: expected exactly 1 checkpoint in $SRC, found $NCKPT"
  exit 1
fi
echo "Warm-starting from: $(ls -d "$SRC"/checkpoint-*)"

# ── queue: most decisive LR first ──────────────────────────────────────────
for LR in ${LRS:-1e-04 3e-04}; do
  RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
  RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
  RUN_NAME="${RUN_NAME}_WSfromN16lr${SRC_LR}"
  RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

  EXP_PATH="./runs-rmmv5p7-warmstart/${DATA_PATH}/${RUN_NAME}/run_${RUN_IDX}"
  if [ -d "$EXP_PATH" ]; then
    echo "Skipping existing: $EXP_PATH"
    continue
  fi

  echo "=== [W2 seed ${SEED}] Launching: $EXP_PATH"
  accelerate launch \
    --main_process_port 0 \
    --num_processes $NP \
    --mixed_precision bf16 \
    --config_file accelerate.yaml \
    run_rmm_on_kv_retrieval-v5p7.py \
    --exp_path                    "$EXP_PATH" \
    --model_cpt                   "$SRC" \
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
    --seed                        $SEED
  echo "=== [W2 seed ${SEED}] lr=$LR exit=$?"
done

echo "W2 done"
