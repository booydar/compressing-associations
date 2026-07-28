#!/bin/bash
set -e

# ── HEDGE: more seeds on the best correct-state compressed result at N16 ─────
#
# This is NOT part of the v6p6 story. It is the fallback number for the write-up
# if v6p6 does not land in time, and it runs concurrently from the start.
#
# v6p4-armt is the strongest N16 compressed cell among models with the CORRECT
# GDN state (v6p0/p1/p2 froze GDN at FLA defaults, ~786k/layer instead of 128, so
# their 99s are not usable). Current evidence, M=8 / identity->self_attn / ss32:
#
#   lr 1e-04   seeds (90.70, 49.46)   mean 70.08
#   lr 3e-04   seeds (91.54, 27.80)   mean 59.67
#
# Two LRs, each with one seed at ~91 and one collapsed. That is the beta_L0
# write-gate death signature, not a capacity ceiling -- and with n=2 it is not
# reportable. Four more seeds per LR turns "70.08 +- 20" into "escapes k/6 runs,
# reaching ~91 when it does", with the failure mode already characterised.
#
# Same config as scripts/assoc-comp-rmm/run_rmm_v6p4_armt_on_kv_retrieval-id-selfattn.sh,
# restricted to N16 and to seed indices that do not collide with the existing
# run_1 / run_2. Writes to runs-rebuttal/ so the published runs are untouched.
#
# Env overrides:
#   RUNS="3 4 5 6"       seed indices (seed = 142 + N); 1,2 already exist
#   LRS="1e-04 3e-04"    learning rates
#
# Usage:
#   CUDA_VISIBLE_DEVICES=1 RUNS="3 4" ./run_v6p4armt_N16_seeds.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4
H=4                     # kept at 4 to match the existing runs this extends.
                        # NB H is an open confound: on the v5p7 identity cell
                        # H=1 -> 97.96 and H=4 -> 81.68. Do not "fix" it here or
                        # seeds 3-6 stop being comparable to seeds 1-2.
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
NUM_COMPRESS_HEADS=4    # unused in self_attn; kept for run-name parity
STATE_SIZE=32

WRITE_MODE=self_attn
READ_MODE=identity
THREAD_MEMORY=False
USE_PARALLEL_PREFILL=False   # forced False in-model for self_attn

K=2
V=2
N_PAIRS=16
NUM_MEMORY_VECTORS=8
TOKENS_PER_SEGMENT=7
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))

for LR in ${LRS:-1e-04 3e-04}; do
  for N in ${RUNS:-3 4 5 6}; do

    RUN_NAME="rmmv6p4armt_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
    RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
    RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

    EXP_PATH="./runs-rebuttal/rmmv6p4-armt-seeds/${DATA_PATH}/${RUN_NAME}/run_${N}"
    if [ -d "$EXP_PATH" ]; then
      echo "Skipping existing: $EXP_PATH"
      continue
    fi

    echo "Launching: $EXP_PATH"
    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmm_on_kv_retrieval-v6p4-armt.py \
      --exp_path                    "$EXP_PATH" \
      --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
      --gradient_accumulation_steps $GRAD_ACC_STEPS \
      --total_batch_size            $TBS \
      --data_path                   "./data/${DATA_PATH}" \
      --tokenizer_path              "$TOKENIZER_PATH" \
      --base_model                  $BASE_MODEL \
      --n_layer                     $L \
      --n_head                      $H \
      --num_memory_heads            1 \
      --num_compress_heads          $NUM_COMPRESS_HEADS \
      --n_embd                      $D \
      --fla_layer                   $FLA_LAYER \
      --state_size                  $STATE_SIZE \
      --expand_v                    $EXPAND_V \
      --conv_kernel                 $CONV_KERNEL \
      --num_memory_vectors          $NUM_MEMORY_VECTORS \
      --write_mode                  $WRITE_MODE \
      --read_mode                   $READ_MODE \
      --thread_memory               $THREAD_MEMORY \
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
      --seed                        $((142 + N))
  done
done

echo "v6p4armt seed worker done (RUNS='${RUNS:-3 4 5 6}' LRS='${LRS:-1e-04 3e-04}')"
