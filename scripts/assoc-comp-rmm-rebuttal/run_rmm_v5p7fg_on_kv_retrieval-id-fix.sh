#!/bin/bash
set -e

# v5p7fg diagnostic: does the store-floor fix remove the N32 seed collapse?
#
# Diagnosis (2026-07-17): v5p7 identity stores the whole AR task in layer-0's
# GDN (the only layer readable from the QT pass). The un-fixed model dies when
# L0 stops being a store — via write-gate death (beta_L0 -> 0.01) OR retention
# death (alpha_L0 -> 0.44, store parked at unreadable L2; observed under
# fix-v1). Fix v2 in v5p7fg = STORE FLOOR on layer 0 only:
#   training-only hinge penalties on the TOP-10% quantile of both gates,
#     beta:  coef 20 * relu(0.20 - top10%(beta))
#     alpha: coef 20 * relu(0.98 - top10%(alpha))
#   Per-token filtering (beta=0 on noise) and forgetting (fast alpha) remain
#   free everywhere; only "L0 retains nothing" is penalized. b_proj gets a
#   bias term (init 0.0, neutral) as a scalar recovery lever.
#
# Verification matrix (same seeds 143/144 as the original runs):
#   N32 @ lr {1e-04, 5e-05}: v5p7 baseline was bimodal — (94.5, 3.8) and
#     (97.8, 3.8). PASS = both seeds escape the ~3.7-EM plateau and converge.
#   N16 @ lr {1e-04, 5e-05}: regression check — v5p7 was already ~0.98-0.99
#     at 1e-04. PASS = no degradation.
# Results land in ./runs-rmmv5p7fg/ (kept separate from paper runs).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}

# ── resources ──────────────────────────────────────────────────────────────
NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

# ── model ──────────────────────────────────────────────────────────────────
L=4
H=1
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4

# ── v5p7fg store-floor knobs ───────────────────────────────────────────────
GATE_BIAS_INIT=${GATE_BIAS_INIT:-0.0}
STORE_LAYER=${STORE_LAYER:-0}
BETA_FLOOR_TAU=${BETA_FLOOR_TAU:-0.2}
BETA_FLOOR_FRAC=${BETA_FLOOR_FRAC:-0.1}
BETA_FLOOR_COEF=${BETA_FLOOR_COEF:-20.0}
ALPHA_FLOOR_TAU=${ALPHA_FLOOR_TAU:-0.98}
ALPHA_FLOOR_FRAC=${ALPHA_FLOOR_FRAC:-0.1}
ALPHA_FLOOR_COEF=${ALPHA_FLOOR_COEF:-20.0}

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
# lr_scheduler_type=constant_with_warmup -> LR is flat after WARMUP, so cutting
# ITERS short (diagnostic runs) does not distort the schedule seen so far, it
# just ends training earlier at the same LR trajectory.
ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── RMM memory path ────────────────────────────────────────────────────────
WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True

# ── sweep: N32 first (the collapsing config), then N16 regression check ────
# N_PAIRS_LIST / LRS / RUNS are env-overridable so instances can run in
# parallel on one GPU (e.g. RUNS="2 1" puts the collapsing seed 144 first).
for N_PAIRS in ${N_PAIRS_LIST:-32 16}; do
  for LR in ${LRS:-1e-04 5e-05}; do
    for N in ${RUNS:-1 2}; do
      for STATE_SIZE in 32; do
        TOKENS_PER_SEGMENT=$((N_PAIRS * 7))
        PAIRS_PER_SEGMENT=$N_PAIRS

        DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

        RUN_NAME="rmmv5p7fg_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
        RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
        RUN_NAME="${RUN_NAME}_sl${STORE_LAYER}_gb${GATE_BIAS_INIT}_bf${BETA_FLOOR_TAU}x${BETA_FLOOR_COEF}_af${ALPHA_FLOOR_TAU}x${ALPHA_FLOOR_COEF}"
        RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

        EXP_PATH="./runs-rmmv5p7fg/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
          run_rmm_on_kv_retrieval-v5p7fg.py \
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
          --num_memory_vectors          4 \
          --write_mode                  $WRITE_MODE \
          --read_mode                   $READ_MODE \
          --use_parallel_prefill        $USE_PARALLEL_PREFILL \
          --gate_bias_init              $GATE_BIAS_INIT \
          --store_layer                 $STORE_LAYER \
          --beta_floor_tau              $BETA_FLOOR_TAU \
          --beta_floor_frac             $BETA_FLOOR_FRAC \
          --beta_floor_coef             $BETA_FLOOR_COEF \
          --alpha_floor_tau             $ALPHA_FLOOR_TAU \
          --alpha_floor_frac            $ALPHA_FLOOR_FRAC \
          --alpha_floor_coef            $ALPHA_FLOOR_COEF \
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

echo "Done"
