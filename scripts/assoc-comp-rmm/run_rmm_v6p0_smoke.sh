#!/bin/bash
set -e

# v6p0 smoke: disentangled read/write memory. Single short config on
# N8-K2V2-V62_1M to confirm the model trains (loss down, EM up) and the
# parallel-prefill path runs. Not a real sweep.
#
# Per-layer order: ATTN -> COMPRESS(write) -> GDN scan[R reads, M writes]
#                  -> read g = GDN read-outputs of S_{s-1} -> DECOMPRESS(g) -> residual.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
# Pin a single GPU: with >1 visible GPU, HF Trainer wraps the model in
# nn.DataParallel, and `next(self.model.parameters())` inside parallel_forward
# raises StopIteration in the DP replicas. Single GPU is plenty for a smoke run.
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
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
STATE_SIZE=32

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
N_PAIRS=8
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── RMM v6p0 memory path ────────────────────────────────────────────────────
WRITE_MODE=pool
READ_MODE=unpool
NUM_MEMORY_VECTORS=16
USE_PARALLEL_PREFILL=True

# ── training (SMOKE: short) ──────────────────────────────────────────────────
LR=3e-04
ITERS=${ITERS:-400}
WARMUP=40
EVAL_STEPS=100
EARLY_STOP=1000
TOKENS_PER_SEGMENT=14

DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"
RUN_NAME="rmmv6p0_smoke_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${WRITE_MODE}_${READ_MODE}_tps${TOKENS_PER_SEGMENT}"
EXP_PATH="./runs-rmmv6p0-smoke/${DATA_PATH}/${RUN_NAME}"

echo "Launching SMOKE: $EXP_PATH"
accelerate launch \
  --main_process_port 0 \
  --num_processes $NP \
  --mixed_precision bf16 \
  --config_file accelerate.yaml \
  run_rmm_on_kv_retrieval-v6p0.py \
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
  --seed                        142

echo "Done"
