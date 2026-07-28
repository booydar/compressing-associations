#!/bin/bash
# Parameterized N32 token-level warm-start. Generalizes
# run_rmm_v5p7_N32_warmstart-s14{3,4}.sh, which hardcoded SEED and SRC_LR=1e-04.
#
# Two axes this opens up:
#   SEED   -- new seeds (needs a matching N16 source; see run_rmm_v5p7_N16_src_param.sh)
#   SRC_LR -- which N16 checkpoint we bootstrap from. All six existing sources
#             are converged (EM 0.987-0.992) but only SRC_LR=1e-04 was ever
#             used, so "the rescue depends on one lucky source checkpoint" is
#             currently unfalsified.
#
# Env: SEED (143), SRC_LR (1e-04), LRS ("3e-04"), ITERS (60000), CUDA_VISIBLE_DEVICES.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# fla env holds the fla/GDN library + accelerate for v5p7 (see reference-remote-layout)
export PATH="$HOME/envs/fla/bin:$PATH"
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}

SEED=${SEED:-143}
RUN_IDX=$(( SEED - 142 ))
SRC_LR=${SRC_LR:-1e-04}
ITERS=${ITERS:-60000}
WARMUP=${WARMUP:-2000}
EVAL_STEPS=500
EARLY_STOP=500

NP=${NP:-1}
TBS=64
PER_DEVICE_BATCH_SIZE=64
GRAD_ACC_STEPS=$(( TBS / (PER_DEVICE_BATCH_SIZE * NP) ))

L=4; H=1; D=128
BASE_MODEL=llama
FLA_LAYER=GatedDeltaNet
EXPAND_V=2.0
CONV_KERNEL=4
STATE_SIZE=32
NUM_MEMORY_VECTORS=32

K=2; V=2; N_PAIRS=32
TOKENIZER_PATH="./tokenizers/kv_alphabet_62/"
DATA_PATH="N${N_PAIRS}-K${K}V${V}-V62_1M"

WRITE_MODE=identity
READ_MODE=identity
USE_PARALLEL_PREFILL=True
TOKENS_PER_SEGMENT=7
PAIRS_PER_SEGMENT=1

SRC="./runs-rebuttal/rmmv5p7/N16-K2V2-V62_1M/rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}_lr${SRC_LR}_bs${TBS}_pps1_tps7/run_${RUN_IDX}"

if [ ! -d "$SRC" ]; then
  echo "FATAL: source checkpoint dir not found: $SRC"; exit 1
fi
NCKPT=$(ls -d "$SRC"/checkpoint-* 2>/dev/null | wc -l)
if [ "$NCKPT" -ne 1 ]; then
  echo "FATAL: expected exactly 1 checkpoint in $SRC, found $NCKPT"; exit 1
fi
echo "Warm-starting seed ${SEED} from: $(ls -d "$SRC"/checkpoint-*)"

for LR in ${LRS:-3e-04}; do
  RUN_NAME="rmmv5p7_${FLA_LAYER}_${BASE_MODEL}_L${L}H${H}D${D}"
  RUN_NAME="${RUN_NAME}_ss${STATE_SIZE}_M0_${READ_MODE}_${WRITE_MODE}"
  RUN_NAME="${RUN_NAME}_WSfromN16lr${SRC_LR}"
  RUN_NAME="${RUN_NAME}_lr${LR}_bs${TBS}_pps${PAIRS_PER_SEGMENT}_tps${TOKENS_PER_SEGMENT}"
  EXP_PATH="./runs-rmmv5p7-warmstart/${DATA_PATH}/${RUN_NAME}/run_${RUN_IDX}"

  if [ -d "$EXP_PATH" ]; then echo "Skipping existing: $EXP_PATH"; continue; fi

  echo "=== [WS seed ${SEED} src ${SRC_LR}] Launching: $EXP_PATH (ITERS=$ITERS)"
  accelerate launch \
    --main_process_port 0 --num_processes $NP --mixed_precision bf16 \
    --config_file accelerate.yaml \
    run_rmm_on_kv_retrieval-v5p7.py \
    --exp_path "$EXP_PATH" --model_cpt "$SRC" \
    --per_device_batch_size $PER_DEVICE_BATCH_SIZE \
    --gradient_accumulation_steps $GRAD_ACC_STEPS \
    --total_batch_size $TBS \
    --data_path "./data/${DATA_PATH}" \
    --tokenizer_path "$TOKENIZER_PATH" \
    --base_model $BASE_MODEL --n_layer $L --n_head $H --n_embd $D \
    --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V \
    --conv_kernel $CONV_KERNEL --num_memory_vectors $NUM_MEMORY_VECTORS \
    --write_mode $WRITE_MODE --read_mode $READ_MODE \
    --use_parallel_prefill $USE_PARALLEL_PREFILL \
    --tokens_per_segment $TOKENS_PER_SEGMENT \
    --n_pairs $N_PAIRS --n_keys $K --n_values $V \
    --learning_rate $LR --max_steps $ITERS --warmup_steps $WARMUP \
    --eval_steps $EVAL_STEPS --logging_steps $EVAL_STEPS \
    --early_stopping_patience $EARLY_STOP --seed $SEED
  echo "=== [WS seed ${SEED} src ${SRC_LR}] lr=$LR exit=$?"
done
echo "warmstart_param done"
