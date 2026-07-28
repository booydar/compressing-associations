#!/bin/bash
# SEED-SWEEP WORKER (workers W3/W4/W5) — N32 token-level RMM, collapse frequency.
#
# WHY: every instability claim in the paper currently rests on n=2 seeds, and the
# N32 pattern is not "50% of seeds fail" but "seed 144 fails in EVERY cell (all
# LRs, tps7 and tps224) while seed 143 succeeds in 4 of 6". With n=2 that is an
# anecdote. It is also what makes §4.2 unsound: the 1-pair noisy-AR row is the
# mean of one healthy seed (91.4) and one collapsed seed (25.4), so the headline
# "coarser writes generalize better OOD" does not survive best-of-n reporting.
#
# This sweep adds seeds 145-150 (run_3..run_8) to the existing run_1/run_2, giving
# n=8 and turning COLLAPSE FREQUENCY into the reported quantity — which is both
# more informative than mean or best-of-n alone, and is the paper's actual claim.
# Pair with run_gdn_N32_seedsweep.sh for the "k/8 vs 0/n" contrast.
#
# BUDGET: 100k steps, vs 200k for the existing run_1/run_2 (recorded in each
# run's config.json). Justification: escapes from the plateau are sudden, and at
# this LR the only observed escape was at step 44.5k; the latest escape ever seen
# in this task family was 87.5k, at a 20x lower LR. 100k therefore classifies
# every trajectory observed to date identically to a 200k budget, at half the
# cost. Report the budget with the collapse frequency.
#
# USAGE — one instance per worker thread, each with its own slice of the queue:
#   CUDA_VISIBLE_DEVICES=1 RUNS="3 4" ./run_rmm_v5p7_N32_seedsweep.sh
#   CUDA_VISIBLE_DEVICES=1 RUNS="5 6" ./run_rmm_v5p7_N32_seedsweep.sh
#   CUDA_VISIBLE_DEVICES=0 RUNS="7 8" ./run_rmm_v5p7_N32_seedsweep.sh
# Runs within one instance are SEQUENTIAL by design: past GPU saturation extra
# concurrency delays every result equally instead of finishing any of them sooner.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}

# No `set -e`: queue worker, one failing cell must not kill the rest.

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
STATE_SIZE=32
NUM_MEMORY_VECTORS=32

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
N_PAIRS=32
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

# ── memory path: the token-level endpoint ──────────────────────────────────
WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True
TOKENS_PER_SEGMENT=7          # 1 KV pair per segment
PAIRS_PER_SEGMENT=1

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-100000}
WARMUP=10000                  # unchanged from the from-scratch baseline
EVAL_STEPS=500
EARLY_STOP=500                # 500 evals x 500 steps = 250k, never fires at 100k

# lr1e-03 is the cell that produced the best from-scratch token-level result
# (87.7 on seed 143); it is the config the collapse frequency should describe.
for LR in ${LRS:-1e-03}; do
  for N in ${RUNS:-3 4 5 6 7 8}; do
    SEED=$(( 142 + N ))

    RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
    RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
    RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

    # Same directory as the existing run_1/run_2 so the whole seed population
    # collects with a single glob.
    EXP_PATH="./runs-rebuttal/rmmv5p7/${DATA_PATH}/${RUN_NAME}/run_${N}"
    if [ -d "$EXP_PATH" ]; then
      echo "Skipping existing: $EXP_PATH"
      continue
    fi

    echo "=== [seedsweep run_${N} seed ${SEED}] Launching: $EXP_PATH"
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
      --seed                        $SEED
    echo "=== [seedsweep run_${N} seed ${SEED}] lr=$LR exit=$?"
  done
done

echo "seedsweep worker done (RUNS='${RUNS:-3 4 5 6 7 8}')"
