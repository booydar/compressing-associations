#!/bin/bash
set -e

# v6p2: v6p0 identity-read + a conv gap between the read and write tokens.
# The single [reads(T), writes(M)] GDN scan let the causal short conv fold raw
# read (segment) tokens into the first writes, leaking them into the recurrent
# state (39-99% on a trained ckpt). v6p2 inserts gap_width = conv_size+1 zero,
# read-masked tokens -> [reads | gap | writes] so the write conv can't reach a
# read token; the written state becomes a pure function of the compressed
# writes. Keeps the single batched scan (no v6p1 4x). gap_width auto-resolves
# in the model (conv_size+1); nothing to pass here.

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
NUM_COMPRESS_HEADS=4

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── RMM v6p2 memory path ───────────────────────────────────────────────────
WRITE_MODE=cross_attn_tf
READ_MODE=identity
THREAD_MEMORY=True     # v6p4 cross-layer query threading
USE_PARALLEL_PREFILL=True

# ── sweep ──────────────────────────────────────────────────────────────────
for LR in 3e-04 1e-04; do
  for NUM_MEMORY_VECTORS in 32; do
    for N in 1 2; do
      for N_PAIRS in 16 8; do
        for TOKENS_PER_SEGMENT in 7; do
          for STATE_SIZE in 32; do

            DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"
            PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))

            RUN_NAME="rmmv6p5_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}NCH${NUM_COMPRESS_HEADS}"
            RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
            THR_TAG=$([ "$THREAD_MEMORY" = "True" ] && echo thrON || echo thrOFF)
            RUN_NAME="${RUN_NAME}_${THR_TAG}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

            EXP_PATH="./runs-rmmv6p5/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
              run_rmm_on_kv_retrieval-v6p5.py \
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
      done
    done
  done
done

echo "Done"
