#!/bin/bash
set -e

# Run from repo root so ./data, ./tokenizers, accelerate.yaml, and the trainer resolve.
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
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── RMM v5 memory path (fixed; edit here to change experiment) ──
WRITE_MODE=pool
READ_MODE=unpool

# ── sweep ──────────────────────────────────────────────────────────────────
# PAIRS_PER_SEGMENT : KV pairs per context chunk (same role as v3 pairs_per_segment)
# TOKENS_PER_SEGMENT: v5 collator splits encoded context into chunks of this many tokens.
#   Matches v3 segment length for pairs "!K:V!" concatenated P times:
#   one pair = K + V + 4 chars (! : !); P pairs ⇒ P * (K + V + 4) (char-level tokenizer ≈ tokens).
# STATE_SIZE        : GDN state dim = num_heads * head_dim (must divide by H)
# NUM_MEMORY_VECTORS: passed for CLI compatibility; ignored when write_mode=identity

for N_PAIRS in 4 8; do
  for N in 1 2; do
    for PAIRS_PER_SEGMENT in 1 4; do
      for STATE_SIZE in 32; do
        for NUM_MEMORY_VECTORS in 1 4; do
          for LR in 3e-04 1e-04 5e-05; do

            DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"
            TOKENS_PER_SEGMENT=$(( PAIRS_PER_SEGMENT * (K + V + 3) ))

            RUN_NAME="rmmv5_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
            RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
            RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

            EXP_PATH="./runs-rmmv5/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
              run_rmm_on_kv_retrieval-v5.py \
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
