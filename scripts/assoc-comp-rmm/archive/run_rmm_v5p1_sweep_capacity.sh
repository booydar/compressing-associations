#!/bin/bash
set -e

# v5p1 sweep — CAPACITY axes (M × write_value_dim × LR × N).
# Goal: chart EM as a function of write throughput (M) and GDN hidden width
# (write_value_dim) at N=4 and N=8, holding state_size=32 fixed.
# Pairs with run_rmm_v5p1_sweep_mech.sh which sweeps the mechanism knobs.

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
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
TOKENS_PER_SEGMENT=1   # pool-1tps regime

# ── training (autoresearch budget) ─────────────────────────────────────────
ITERS=25000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=20

# ── memory path (cross_attn ↔ M>1 requires cross_attn write) ───────────────
WRITE_MODE=cross_attn
READ_MODE=cross_attn
NUM_MEMORY_HEADS=4
WRITE_RESIDUAL=false

# ── sweep ──────────────────────────────────────────────────────────────────
SEEDS=${SEEDS:-"1 2"}

for N_PAIRS in 4 8; do
  for NUM_MEMORY_VECTORS in 1 4 8; do
    for WRITE_VALUE_DIM in 128 256 512; do
      for LR in 3e-04 1e-04; do
        for N in $SEEDS; do
          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

          RUN_NAME="rmmv5p1_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
          RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}H${NUM_MEMORY_HEADS}_${WRITE_MODE}-wvd${WRITE_VALUE_DIM}"
          RUN_NAME="${RUN_NAME}_ev${EXPAND_V}_ck${CONV_KERNEL}_lr${LR}_bs${TBS}_tps${TOKENS_PER_SEGMENT}"

          EXP_PATH="./runs-rmmv5p1-sweep-cap/${DATA_PATH}/${RUN_NAME}/run_${N}"
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

echo "Done"
