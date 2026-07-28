#!/bin/bash
set -e

# ── v6p4 compressed WRITE + token-level READ, at the GDN baseline's state budget ─
#
# THE CLAIM THIS TESTS
#   Compression on the WRITE side is survivable; compressed READ (unpool) is what
#   breaks. v6p4 read_mode=identity is the only implementation of a true token-level
#   read in the repo: the read positions ARE the tokens, so the token's own content
#   queries the recurrent state (huggingface_rmm_v6p4.py:99-100, 373).
#   For contrast, every v6p6 read mode -- unpool, cross_attn, cross_attn_tf -- reads
#   from `g`, which is R *static* learned queries applied to the state
#   (huggingface_rmm_v6p6.py:616, 736). No token content enters the state query, so
#   v6p6 cannot test this claim at all.
#
# WHY THE EXISTING N16 CELL DOES NOT ALREADY ANSWER IT
#   runs-rmmv6p4/N16-.../M32_identity_pool_lr3e-04/:
#       run_1  EM 0.08  killed at  34000 steps
#       run_2  EM 0.10  killed at  48000 steps
#   Nothing in this task family has ever escaped chance that early: v5p4's N16
#   compressed cell needed 118.5k, v6p6 M=7 needed ~70-100k. The lr1e-04 arm is in
#   that script's loop but never ran. Meanwhile the SAME config at N8 reaches 93.18
#   at 199k -- the path works, N16 was simply never trained.
#   It is also a single sample at (M=32, lr3e-04), both known-worst coordinates:
#       LR at N16, M=32, 512 state:  v6p5 45.90 @1e-04 vs 1.94 @3e-04   (24x)
#       M  at N16, lr1e-04:          v5p4 55.08 @M8   vs 7.89 @M32      (7x)
#   v6p4-armt's working point is M=8 / lr1e-04. This script starts there.
#
# STATE BUDGET -- the reason for the H/ss pairs below
#   head_dim = state_size // n_head  (run_rmm_on_kv_retrieval-v6p4.py:316), and the
#   GDN recurrent state is num_heads * head_k_dim * head_v_dim with
#   head_v_dim = head_dim * expand_v, so
#
#       state/layer = state_size^2 * expand_v / n_head
#
#   n_head is a STATE knob, not a free architectural choice. At expand_v=2.0:
#       PAPER GDN baseline ss32 H1  -> 2048   <- runs-rebuttal-default-sv/, the
#                                                budget everything must match
#       this script        ss32 H1  -> 2048   <- identical to that baseline
#       alt head count     ss64 H4  -> 2048   <- same budget, different head split
#       v5p4 "55.08"       ss32 H1  -> 2048   (correctly matched)
#       v5p7 "97.96"       ss32 H1  -> 2048   (correctly matched)
#       ALL v6p4/p5/armt   ss32 H4  ->  512   (1/4 budget -- under-provisioned!)
#       smaller baseline   ss16 H1  ->  512   (runs-rebuttal-default/, NOT the
#                                                paper baseline; do not target it)
#
#   Every existing v6 run is at 512 -- a quarter of the baseline and a quarter of
#   the v5p4 row it is meant to beat. That alone may account for v6p4-armt 70.08
#   and v6p5 45.90 at N16. H=1/ss32 fixes it and is also the head count that has
#   optimized better throughout.
#
#   CFGS="1:32 4:64" runs both head counts at a fixed 2048 -- the first clean test
#   of head count on its own, since every H=1 win so far was also a 4x-state win
#   (v5p7 97.96 at H1/2048 vs 81.68 at H4/512).
#
#   The budget is enforced below; the script aborts rather than silently drifting
#   off it, because that is the comparison the whole table rests on.
#   Cross-check the formula against notebooks/debug_rmmv5.ipynb before trusting it.
#
# WHAT TO BEAT (all at the 2048 budget, 200k steps)
#       GDN baseline  N16  98.92 / 99.84 / 99.78 / 99.30      N32  97.90 / 98.92 / 98.44 / 94.88
#       v5p7 identity N16  97.96 / 99.02                      N32  good seed ~97.8 (bimodal)
#       v5p4 compressed-READ  N16  55.08                      <- the gap this run targets
#   Plain GDN solves both tasks, so the claim is parity-at-equal-state for a
#   segment-wise model with a COMPRESSED memory -- not beating GDN.
#
# Env overrides:
#   CFGS="1:32"           H:ss pairs. 1:32 and 4:64 are both 2048/layer.
#   MS="8"                memory vectors (compression: M=8 for a 16-pair table)
#   LRS="1e-04 5e-05"     learning rates. 3e-04 is known-bad at N16; not a default.
#   RUNS="1 2"            seed indices (seed = 142 + N)
#   NPAIRS="16"           16 first; 32 is the follow-on once N16 is in hand
#   ITERS=200000          escape has taken up to 118.5k here -- do not shorten
#   STATE_BUDGET=2048     set to 0 to disable the budget check
#
# Usage -- 2 GPUs, 3 workers each, one run per worker:
#   cd scripts/assoc-comp-rmm-rebuttal
#   CUDA_VISIBLE_DEVICES=0 LRS=1e-04 RUNS=1 ./run_rmm_v6p4_idpool_statematched.sh &
#   CUDA_VISIBLE_DEVICES=0 LRS=1e-04 RUNS=2 ./run_rmm_v6p4_idpool_statematched.sh &
#   CUDA_VISIBLE_DEVICES=0 LRS=5e-05 RUNS=1 ./run_rmm_v6p4_idpool_statematched.sh &
#   CUDA_VISIBLE_DEVICES=1 LRS=5e-05 RUNS=2 ./run_rmm_v6p4_idpool_statematched.sh &
#   CUDA_VISIBLE_DEVICES=1 CFGS=4:64 LRS=1e-04 RUNS=1 ./run_rmm_v6p4_idpool_statematched.sh &
#   CUDA_VISIBLE_DEVICES=1 CFGS=4:64 LRS=1e-04 RUNS=2 ./run_rmm_v6p4_idpool_statematched.sh &
#
# Read out with: scripts/assoc-comp-rmm-rebuttal/v6p6-unified/collect_v6p6.py \
#                    --root runs-rebuttal/rmmv6p4-idpool
# Watch token_accuracy, not EM -- EM ~= tokacc^2 across this whole grid, so EM
# squares away the signal you need to call a cell early.

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
D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4

# ── memory path: compressed write, token-level read ────────────────────────
WRITE_MODE=pool
READ_MODE=identity        # the read positions ARE the tokens -> content-addressed
THREAD_MEMORY=True        # v6p4 cross-layer query threading
USE_PARALLEL_PREFILL=True

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
TOKENS_PER_SEGMENT=7      # 1 KV pair per segment

# ── training ───────────────────────────────────────────────────────────────
ITERS=${ITERS:-200000}
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

STATE_BUDGET=${STATE_BUDGET:-2048}

for CFG in ${CFGS:-1:32}; do
  H="${CFG%%:*}"
  STATE_SIZE="${CFG##*:}"

  # state/layer = state_size^2 * expand_v / n_head  -- awk because expand_v is float
  STATE_PER_LAYER=$(awk -v s="$STATE_SIZE" -v h="$H" -v e="$EXPAND_V" 'BEGIN{printf "%d", s*s*e/h}')
  if [ $(( STATE_SIZE % H )) -ne 0 ]; then
    echo "ABORT: state_size=$STATE_SIZE not divisible by n_head=$H (head_dim would truncate)"
    exit 1
  fi
  if [ "$STATE_BUDGET" -ne 0 ] && [ "$STATE_PER_LAYER" -ne "$STATE_BUDGET" ]; then
    echo "ABORT: H=$H ss=$STATE_SIZE gives ${STATE_PER_LAYER}/layer, budget is ${STATE_BUDGET}."
    echo "       The paper GDN baseline is ss32/H1 = 2048. Off-budget rows are not"
    echo "       comparable to it. Re-run with STATE_BUDGET=0 if that is intended."
    exit 1
  fi
  echo "=== H=$H ss=$STATE_SIZE  ->  ${STATE_PER_LAYER} state/layer (budget ${STATE_BUDGET}) ==="

  for N_PAIRS in ${NPAIRS:-16}; do
    for NUM_MEMORY_VECTORS in ${MS:-8}; do
      for LR in ${LRS:-1e-04 5e-05}; do
        for N in ${RUNS:-1 2}; do

          DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"
          PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))

          RUN_NAME="rmmv6p4_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
          RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
          THR_TAG=$([ "$THREAD_MEMORY" = "True" ] && echo thrON || echo thrOFF)
          RUN_NAME="${RUN_NAME}_${THR_TAG}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

          EXP_PATH="./runs-rebuttal/rmmv6p4-idpool/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
            run_rmm_on_kv_retrieval-v6p4.py \
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

echo "idpool worker done (CFGS='${CFGS:-1:32}' NPAIRS='${NPAIRS:-16}' MS='${MS:-8}' LRS='${LRS:-1e-04 5e-05}' RUNS='${RUNS:-1 2}')"
