#!/bin/bash
# WORKER W6 — pure GDN baseline at N32, extra seeds.
#
# WHY: the paper's claim is "the token-level RMM endpoint reaches GDN's ceiling
# but from a smaller basin of attraction". That is a CONTRAST, so it needs a seed
# population on both sides. On disk GDN N32/ss32/ck4 is 4/4 (0.979, 0.989 at
# lr1e-3; 0.984, 0.949 at lr3e-4) but that is only run_1/run_2 per LR — the same
# n=2 problem the RMM side has. This adds run_3..run_6 at lr1e-3 for n=6.
#
# Mechanistically GDN is expected to be immune (project_rmm_hybrid_vs_gdn_gap):
# o = q.S IS the layer's only token mixer, so writes are load-bearing for every
# prediction from step 0 and cannot be gated away, and it has redundant no-decay
# stores at L0 and L2. Measuring 0/6 rather than asserting it is the point.
#
# NOTE: the FLA baselines read from ./data/ar/ while the RMM runners read from
# ./data/ — both exist for N32, do not "fix" this to match.
#
# BUDGET: 50k steps (existing run_1/run_2 used 200k). Budgets are set per-arm by
# ESCAPE-TIME HEADROOM, not by equality: what makes a "collapse" verdict credible
# is the budget being a large multiple of the observed escape time for that arm.
# GDN escapes at step 3.5-4.5k, so 50k is ~11x headroom; the RMM arm escapes at
# 44.5k at its sweep LR, so its 100k is ~2.2x. Matching both at 100k would spend
# ~28h of GPU on an arm that is already decided by step 5k. State the per-arm
# budget alongside the frequency.
#
# USAGE:
#   CUDA_VISIBLE_DEVICES=0 ./run_gdn_N32_seedsweep.sh
#   CUDA_VISIBLE_DEVICES=0 RUNS="3 4" ./run_gdn_N32_seedsweep.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}

# No `set -e`: queue worker, one failing cell must not kill the rest.

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
ADAM_BETA2=0.999
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model (matches the existing baseline run names exactly) ────────────────
N_LAYER=4
N_HEAD=1
N_EMBD=128
STATE_SIZE=32
CONV_KERNEL=4
BASE_MODEL=gated_delta_net

# ── data ───────────────────────────────────────────────────────────────────
K=2
VOCAB_SIZE=62
N_PAIRS=32
TOKENIZER_PATH="./tokenizers/kv_alphabet_${VOCAB_SIZE}/"
DATA_NAME="N${N_PAIRS}-K${K}V${K}-V${VOCAB_SIZE}_1M"
DATA_PATH="./data/ar/${DATA_NAME}"

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-50000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

for LR in ${LRS:-1e-03}; do
  for N in ${RUNS:-3 4 5 6}; do
    SEED=$(( 142 + N ))

    RUN_NAME="${BASE_MODEL}_L${N_LAYER}D${N_EMBD}_ss${STATE_SIZE}_ck${CONV_KERNEL}"
    RUN_NAME="${RUN_NAME}_bs_${TBS}_lr_${LR}"
    if [ -n "$ADAM_BETA2" ]; then
      RUN_NAME="${RUN_NAME}_b2_${ADAM_BETA2}"
    fi

    # Same directory as the existing run_1/run_2 so the seed population globs together.
    EXP_PATH="./runs-rebuttal-default-sv/${DATA_NAME}/${RUN_NAME}/run_${N}"
    if [ -d "$EXP_PATH" ]; then
      echo "Skipping existing: $EXP_PATH"
      continue
    fi

    echo "=== [gdn seedsweep run_${N} seed ${SEED}] Launching: $EXP_PATH"
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
      --n_layer                     $N_LAYER \
      --n_head                      $N_HEAD \
      --n_embd                      $N_EMBD \
      --state_size                  $STATE_SIZE \
      --conv_kernel                 $CONV_KERNEL \
      --n_pairs                     $N_PAIRS \
      --n_keys                      $K \
      --n_values                    $K \
      --base_model                  $BASE_MODEL \
      --max_steps                   $ITERS \
      --eval_steps                  $EVAL_STEPS \
      --logging_steps               $EVAL_STEPS \
      --warmup_steps                $WARMUP \
      --early_stopping_patience     $EARLY_STOP \
      --seed                        $SEED
    echo "=== [gdn seedsweep run_${N} seed ${SEED}] exit=$?"
  done
done

echo "gdn seedsweep worker done (RUNS='${RUNS:-3 4 5 6}')"
