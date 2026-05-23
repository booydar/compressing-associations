#!/bin/bash
set -e

# Token-level recurrent baselines (GDN, DeltaNet) on KV retrieval.
# Matches the v5p1 sweep ladder: N ∈ {4, 8}, L=4, H=4, D=128, bs=64.
# Sweeps state_size to draw the capacity curve for RD §3.1
# (capacity-matched comparison against ARMT/RMM v5p1).
# ~24 runs at 2 seeds.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))
ADAM_BETA2=0.999

# ── model (locked to v5p1 ladder) ──────────────────────────────────────────
L=4
H=4
D=128
CONV_KERNEL=4

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
VOCAB_SIZE=62
TOKENIZER_PATH="./tokenizers/kv_alphabet_${VOCAB_SIZE}/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=25000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=20
LR=3e-04

SEEDS=${SEEDS:-"1 2"}
BASE_MODELS=${BASE_MODELS:-"gated_delta_net delta_net"}

# ── sweep ──────────────────────────────────────────────────────────────────
for BASE_MODEL in $BASE_MODELS; do
  for N_PAIRS in 4 8; do
    for STATE_SIZE in 4 16 32; do
      for N in $SEEDS; do
        DATA_NAME="N${N_PAIRS}-K${K}V${V}-V${VOCAB_SIZE}_1M"
        # Prefer ./data/ar/, fall back to ./data/
        if [ -d "./data/ar/${DATA_NAME}" ]; then
          DATA_PATH="./data/ar/${DATA_NAME}"
        else
          DATA_PATH="./data/${DATA_NAME}"
        fi

        RUN_NAME="${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_ck${CONV_KERNEL}_lr${LR}_bs${TBS}_b2_${ADAM_BETA2}"
        EXP_PATH="./runs-baselines-token/${DATA_NAME}/${RUN_NAME}/run_${N}"
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
          run_fla_on_kv_retrieval-default.py \
          --exp_path                    "$EXP_PATH" \
          --per_device_batch_size       $PER_DEVICE_BATCH_SIZE \
          --gradient_accumulation_steps $GRAD_ACC_STEPS \
          --total_batch_size            $TBS \
          --data_path                   "$DATA_PATH" \
          --tokenizer_path              "$TOKENIZER_PATH" \
          --learning_rate               $LR \
          --adam_beta2                  $ADAM_BETA2 \
          --n_layer                     $L \
          --n_head                      $H \
          --n_embd                      $D \
          --state_size                  $STATE_SIZE \
          --conv_kernel                 $CONV_KERNEL \
          --n_pairs                     $N_PAIRS \
          --n_keys                      $K \
          --n_values                    $V \
          --base_model                  $BASE_MODEL \
          --max_steps                   $ITERS \
          --eval_steps                  $EVAL_STEPS \
          --logging_steps               $EVAL_STEPS \
          --warmup_steps                $WARMUP \
          --early_stopping_patience     $EARLY_STOP \
          --seed                        $((142 + N))
      done
    done
  done
done

echo "Done"
