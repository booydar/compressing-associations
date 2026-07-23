#!/bin/bash
set -e

# v5p7: v5p4 with per-layer double-residual bug fixed (single skip at call site,
# RecurrentLayerWithSkip wrapper removed). Identity formula now:
#   out_h = post_attn + GDN(LN_f(post_attn))
# instead of v5p4's
#   out_h = post_attn + LN_f(post_attn) + GDN(LN_f(post_attn))
#
# LR sweep extended to include 1e-03 (GDN-baseline LR). H=1 added to a separate
# pass at the bottom for fair comparison vs the 95.84-EM GDN baseline (which
# used H=1, head_dim=32). Default H=4 sweep kept for continuity with v5p4 runs.

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

# ── RMM v5p4 memory path ───────────────────────────────────────────────────
WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True

# ── sweep ──────────────────────────────────────────────────────────────────
for LR in 1e-05 5e-05 1e-04 3e-04 5e-04 7e-04 1e-03; do
  for N in 1 2; do
    for N_PAIRS in 8; do
      for NUM_MEMORY_VECTORS in 32; do
        for STATE_SIZE in 32; do
          TOKENS_PER_SEGMENT=$((N_PAIRS * 7))
          PAIRS_PER_SEGMENT=$N_PAIRS


          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

          RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
          RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
          RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

          EXP_PATH="./runs-rebuttal/rmmv5p7/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
            run_rmm_on_kv_retrieval-v5p7.py \
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
            --seed                        $((142 + N))
          done
        done
      done
    done
  done
done


# ── H=1 head-dim-matched pass (for parity with H=1/head_dim=32 GDN baseline) ──
H_HMATCH=1
for LR in 1e-03 3e-04; do
  for N in 1 2; do
    for N_PAIRS in 16; do
      for NUM_MEMORY_VECTORS in 4; do
        for STATE_SIZE in 32; do
          TOKENS_PER_SEGMENT=$((N_PAIRS * 7))
          PAIRS_PER_SEGMENT=$N_PAIRS

          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

          RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H_HMATCH}D${D}"
          RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
          RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

          EXP_PATH="./runs-rmmv5p7/${DATA_PATH}/${RUN_NAME}/run_${N}"
          if [ -d "$EXP_PATH" ]; then
            echo "Skipping existing: $EXP_PATH"
            continue
          fi

          echo "Launching (H=1 parity): $EXP_PATH"
          accelerate launch \
            --main_process_port 0 \
            --num_processes $NP \
            --mixed_precision bf16 \
            --config_file accelerate.yaml \
            run_rmm_on_kv_retrieval-v5p7.py \
            --exp_path                    "$EXP_PATH" \
            --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
            --gradient_accumulation_steps $GRAD_ACC_STEPS \
            --total_batch_size            $TBS \
            --data_path                   "./data/${DATA_PATH}" \
            --tokenizer_path              "$TOKENIZER_PATH" \
            --base_model                  $BASE_MODEL \
            --n_layer                     $L \
            --n_head                      $H_HMATCH \
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
            --seed                        $((142 + N))
        done
      done
    done
  done
done

echo "Done"
