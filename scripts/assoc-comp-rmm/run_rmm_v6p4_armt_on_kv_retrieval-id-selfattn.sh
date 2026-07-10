#!/bin/bash
set -e

# v6p4-armt: ARMT-faithful bridge model. Segment->memory COMPRESSION is done by the
# base transformer's OWN self-attention (M learnable mem tokens appended per segment,
# exactly like ARMT), and the compressed write vectors update a GatedDeltaNet state
# instead of ARMT's DPFP associative fast-weights. read_mode=identity (the T token
# positions read S_{s-1} via the GDN read-only valve). Goal: make the ONLY intended
# difference vs run_original_armt_on_kv_retrieval-7tps-baseline.sh the recurrent
# operator (GDN vs fast-weights), so any gap is attributable to it.
#
# Differences vs run_rmm_v6p4_on_kv_retrieval-id-ca.sh:
#   * WRITE_MODE=self_attn (was cross_attn) -> no separate MemoryCompress module.
#   * THREAD_MEMORY irrelevant (mem threads natively through the residual stream).
#   * use_parallel_prefill forced False in the model (appended-mem has no parallel path).
#   * N_PAIRS / NUM_MEMORY_VECTORS sweep aligned with the ARMT baseline (N in {4,2},
#     M = n_mem_tokens in {1,2,4,8}, 1 pair per segment ~ tps=7).
#
# NB capacity confound: ARMT per-layer state = 6*d_mem*d_model (+denom) ~ 24.6k at
# d_mem=32; the GDN id-ca state is ~512/layer. Match state_size/expand_v (or ARMT
# d_mem) before reading the result as a clean operator comparison. See
# notebooks/debug_armt_state.ipynb.

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
NUM_COMPRESS_HEADS=4   # unused in self_attn (no MemoryCompress); kept for run-name parity

# ── data ───────────────────────────────────────────────────────────────────
K=2
V=2
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"

# ── training ───────────────────────────────────────────────────────────────
ITERS=200000
WARMUP=10000
EVAL_STEPS=500
EARLY_STOP=500

# ── RMM v6p4-armt memory path ──────────────────────────────────────────────
WRITE_MODE=self_attn   # ARMT-style: base self-attention compresses into mem tokens
READ_MODE=identity
THREAD_MEMORY=False     # native residual-stream threading; flag is a no-op here
USE_PARALLEL_PREFILL=False  # forced False in-model for self_attn anyway

# ── sweep (aligned with run_original_armt_on_kv_retrieval-7tps-baseline.sh) ──
for N in 1 2; do
  for LR in 3e-04 1e-04; do
    for N_PAIRS in 8 16; do
      for NUM_MEMORY_VECTORS in 8; do
        for TOKENS_PER_SEGMENT in 7; do
          for STATE_SIZE in 32; do

            DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"
            PAIRS_PER_SEGMENT=$((TOKENS_PER_SEGMENT / 7))

            RUN_NAME="rmmv6p4armt_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
            RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M${NUM_MEMORY_VECTORS}_${READ_MODE}_${WRITE_MODE}"
            RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"

            EXP_PATH="./runs-rmmv6p4-armt/${DATA_PATH}/${RUN_NAME}/run_${N}"
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
              run_rmm_on_kv_retrieval-v6p4-armt.py \
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
