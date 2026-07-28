#!/bin/bash
set -e

# ── STAGE 3: segmentation ladder at fixed M/T = 1 (deconfound recurrence depth) ─
#
# Table 2 currently varies TWO things at once between its identity and compressed
# columns: the compression ratio M/T *and* the number of recurrent steps. This
# ladder holds M/T = 1 (identity, no compression at all) and walks only the number
# of segments, so any degradation is attributable to recurrence depth alone.
#
#   tps=112  ->  1 context segment    <- from run_v6p6_N16_ctrl_1seg.sh
#   tps= 56  ->  2 segments
#   tps= 28  ->  4 segments
#   tps= 14  ->  8 segments
#   tps=  7  -> 16 segments           <- ALREADY RUN: 50.94 EM / 70.95 tokacc @198.5k
#                                        (runs-rmmv6p6/.../M7_lr3e-04_..._id_init/run_1)
#
# Only the two middle rungs are launched by default; the ends already exist or come
# from stage 1. Five points, one weight set, one state budget, compression held at
# zero. If EM falls off across this ladder, the paper's "compression is the problem"
# framing is wrong and it is recurrence depth -- which is a materially different
# claim and one a reviewer will test.
#
# GATED ON STAGE 1 for the same reason as stage 2, but weakly: the tps=7 endpoint
# is already in hand, so this ladder is still readable even if ctrl underperforms.
# Lower priority than stage 2 if GPU time is short.
#
# CAVEAT on the tps=7 endpoint: the existing run used cap=32, this ladder uses
# cap=112, so the query bank has more rows (more parameters) at the new rungs. The
# bank is sliced to min(M, T) either way, so the active path is unchanged, but the
# endpoint is not bit-for-bit comparable. If the ladder shows a real trend, re-run
# tps=7 at cap=112 for a clean 5th point -- it is one cheap run.
#
# Env overrides:
#   RUNS="1 2"       seed indices (seed = 142 + N)
#   TPSS="56 28"     tokens per segment  (must divide 112 to keep pairs whole)
#   LRS="3e-04"      learning rates -- 3e-04 was best at the tps=7 endpoint
#
# Usage:
#   CUDA_VISIBLE_DEVICES=0 RUNS="1" TPSS="56 28" ./run_v6p6_N16_seg_ladder.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4
H=1
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32

WRITE_MODE=pool
READ_MODE=unpool
IDENTITY_INIT=True

K=2
V=2
N_PAIRS=16
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

MAX_MEMORY_VECTORS=112   # held at the ctrl/ratio capacity so the bank is identical
                         # across every rung; M = T is selected by omitting
                         # --num_memory_vectors, not by shrinking the bank

ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

USE_PARALLEL_PREFILL=True
THREAD_MEMORY=True

for LR in ${LRS:-3e-04}; do
  for N in ${RUNS:-1 2}; do
    for TOKENS_PER_SEGMENT in ${TPSS:-56 28}; do

      if [ $(( (N_PAIRS * 7) % TOKENS_PER_SEGMENT )) -ne 0 ] || [ $(( TOKENS_PER_SEGMENT % 7 )) -ne 0 ]; then
        echo "SKIP tps=$TOKENS_PER_SEGMENT: must be a multiple of 7 and divide $((N_PAIRS*7))"
        continue
      fi

      RUN_NAME="rmmv6p6_${WRITE_MODE}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}"
      RUN_NAME="${RUN_NAME}_cap${MAX_MEMORY_VECTORS}_Midentity_lr${LR}_bs${TBS}_tps${TOKENS_PER_SEGMENT}_id_init"
      EXP_PATH="./runs-rebuttal/rmmv6p6-unified/${DATA_PATH}/${RUN_NAME}/run_${N}"
      if [ -d "$EXP_PATH" ]; then
        echo "Skipping existing: $EXP_PATH"
        continue
      fi

      echo "Launching: $EXP_PATH  ($(( (N_PAIRS*7) / TOKENS_PER_SEGMENT )) context segments)"
      accelerate launch \
        --main_process_port 0 \
        --num_processes $NP \
        --mixed_precision bf16 \
        --config_file accelerate.yaml \
        run_rmm_on_kv_retrieval-v6p6.py \
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
        --max_memory_vectors          $MAX_MEMORY_VECTORS \
        --write_mode                  $WRITE_MODE \
        --read_mode                   $READ_MODE \
        --thread_memory               $THREAD_MEMORY \
        --use_parallel_prefill        $USE_PARALLEL_PREFILL \
        --tokens_per_segment          $TOKENS_PER_SEGMENT \
        --identity_init               $IDENTITY_INIT \
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
        # --num_memory_vectors OMITTED => M = T at every rung.
    done
  done
done

echo "seg_ladder worker done (RUNS='${RUNS:-1 2}' TPSS='${TPSS:-56 28}' LRS='${LRS:-3e-04}')"
