#!/bin/bash
set -e

# v5p1 sweep — MECHANISM axes (write_mode × read_mode × heads × residual ×
# expand_v × conv_kernel). Holds capacity at the autoresearch best
# (M=4, write_value_dim=512) so this sweep isolates the operator choice.
# Run alongside / after run_rmm_v5p1_sweep_capacity.sh.

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
FLA_LAYER=GatedDeltaNet
STATE_SIZE=32

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
TOKENS_PER_SEGMENT=1

# ── training ───────────────────────────────────────────────────────────────
ITERS=25000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=20

# ── capacity held at autoresearch best ─────────────────────────────────────
NUM_MEMORY_VECTORS=4
WRITE_VALUE_DIM=512
LR=3e-04

# ── sweep ──────────────────────────────────────────────────────────────────
SEEDS=${SEEDS:-"1 2"}

# (write_mode, read_mode) compatibility pairs.
#   pool       ↔ unpool        (cheap baseline)
#   cross_attn ↔ unpool        (richer write, simple read)
#   cross_attn ↔ cross_attn    (richer write + read)
# identity/identity skipped — it's the GDN-only ablation, run separately.
PAIRS=(
  "pool unpool 1"
  "cross_attn unpool 1"
  "cross_attn cross_attn 1"
  "cross_attn cross_attn 2"
  "cross_attn cross_attn 4"
)

for N_PAIRS in 4 8; do
  for EXPAND_V in 2.0 4.0; do
    for CONV_KERNEL in 2 4; do
      for WRITE_RESIDUAL in false true; do
        for PAIR in "${PAIRS[@]}"; do
          read -r WRITE_MODE READ_MODE NUM_MEMORY_HEADS <<< "$PAIR"
          for N in $SEEDS; do
            DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

            RUN_NAME="rmmv5p1_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
            RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}H${NUM_MEMORY_HEADS}_${WRITE_MODE}-wvd${WRITE_VALUE_DIM}"
            RUN_NAME="${RUN_NAME}_ev${EXPAND_V}_ck${CONV_KERNEL}_wr${WRITE_RESIDUAL}_lr${LR}_bs${TBS}_tps${TOKENS_PER_SEGMENT}"

            EXP_PATH="./runs-rmmv5p1-sweep-mech/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
              run_rmm_on_kv_retrieval-v5p1.py \
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
              --write_value_dim             $WRITE_VALUE_DIM \
              --num_memory_heads            $NUM_MEMORY_HEADS \
              --write_residual              $WRITE_RESIDUAL \
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
