#!/bin/bash
set -e
# RMM v5p7 (paper version; identity/identity) length-extrapolation eval on babilong.
# Analog of babilong-release
# eval_babilong_qa1_rmt_vary_n_seg_iter_tasks_exp_curriculum.sh:
# load the deepest curriculum-stage checkpoint and evaluate (--validate_only) at
# each MAX_N_SEGMENTS in the extrapolation ladder 1 2 4 8 16 32 64 128 256.
# No training happens and the source checkpoint is never modified; each eval
# writes its metrics into a separate eval_seg<N>_from<SRC> run dir.
#
# Checkpoint selection (see resolve_cpt): prefer the flat model_best.pt written
# when a stage finishes, else fall back to the best HF checkpoint's
# model.safetensors (so a stage that hasn't produced model_best.pt yet can still
# be evaluated). By default the DEEPEST stage with a usable checkpoint is used.
# Overrides (env): MODEL_CPT=<path>  |  SRC_N_SEGMENTS=<n> SRC_PREV_SEG=<m>
#                  LR=<lr>  EVAL_SEGMENTS="1 2 4"  CUDA_VISIBLE_DEVICES / NP
#                  PARALLEL_PREFILL=True  (default False = recurrent; required at >=256 segs)
# Recurrent long-eval variant: default EVAL_SEGMENTS="256 1024". Launch one seg per GPU with EVAL_SEGMENTS="256".

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Single GPU: >1 visible GPU makes HF Trainer wrap the model in nn.DataParallel,
# which trips parallel_forward's next(self.model.parameters()) StopIteration.
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
NP=${NP:-1}

# backbone: pretrained gpt2, as the original babilong experiment
PRETRAINED_MODEL=gpt2
# GDN / RMM v5p7 memory path (must match training exactly for state_dict load)
FLA_LAYER=GatedDeltaNet
H=1                    # GDN heads; head_dim = STATE_SIZE / H
STATE_SIZE=32; EXPAND_V=2.0; CONV_KERNEL=4
WRITE_MODE=identity
READ_MODE=identity
NOISE_DATASET=emozilla/pg19
SEGMENT_SIZE=512

# extrapolation sweep (matches babilong-release short eval); override via env, e.g. EVAL_SEGMENTS="1 2 4"
read -ra EVAL_SEGMENTS <<< "${EVAL_SEGMENTS:-256 1024}"

declare -A TASK_NAMES=(
  [qa1]=qa1_single-supporting-fact
  [qa2]=qa2_two-supporting-facts
  [qa3]=qa3_three-supporting-facts
  [qa4]=qa4_two-arg-relations
  [qa5]=qa5_three-arg-relations
)

N=6
LR=${LR:-1e-05}   # curriculum LR; only used to reconstruct the trained RUN_NAME
TBS=64            # only used to reconstruct the trained RUN_NAME
BS=1              # eval micro-batch size

# resolve_cpt <stage run dir> -> path of the checkpoint to load (or empty).
# 1) model_best.pt  2) best_model_checkpoint's model.safetensors (from the
# newest checkpoint's trainer_state.json)  3) newest checkpoint's safetensors.
resolve_cpt() {
  local d="$1" out="" steps latest_dir best
  if [ -f "$d/model_best.pt" ]; then
    out="$d/model_best.pt"
  else
    steps=$(ls -d "$d"/checkpoint-* 2>/dev/null | sed -E 's#.*/checkpoint-##' | sort -n | tail -1)
    if [ -n "$steps" ]; then
      latest_dir="$d/checkpoint-$steps"
      best=$(grep -o '"best_model_checkpoint": *"[^"]*"' "$latest_dir/trainer_state.json" 2>/dev/null | sed 's/.*: *"//; s/"$//')
      if [ -n "$best" ] && [ -f "$best/model.safetensors" ]; then
        out="$best/model.safetensors"
      elif [ -f "$latest_dir/model.safetensors" ]; then
        out="$latest_dir/model.safetensors"
      fi
    fi
  fi
  echo "$out"
  return 0
}

for task in "qa1"; do
  TASK_DATASET=${TASK_NAMES[$task]}
  RUN_NAME="rmmv5p7_gpt2pre_ss${STATE_SIZE}_${WRITE_MODE}_${READ_MODE}_lr${LR}_bs${TBS}"
  BASE="./runs-rmmv5p7/babilong/${task}/${RUN_NAME}"

  # --- select source checkpoint --------------------------------------------
  if [ -n "${MODEL_CPT:-}" ]; then
    SRC_TAG="${SRC_TAG:-manual}"
  elif [ -n "${SRC_N_SEGMENTS:-}" ]; then
    MODEL_CPT=$(resolve_cpt "${BASE}/seg${SRC_N_SEGMENTS}_from${SRC_PREV_SEG}/run_${N}")
    SRC_TAG="${SRC_N_SEGMENTS}"
  else
    MODEL_CPT=""
    for seg in $(ls -d ${BASE}/seg*_from* 2>/dev/null | sed -E 's#.*/seg([0-9]+)_from[0-9]+#\1#' | sort -rn | uniq); do
      sdir=$(ls -d ${BASE}/seg${seg}_from*/run_${N} 2>/dev/null | head -1)
      [ -z "$sdir" ] && continue
      cand=$(resolve_cpt "$sdir")
      if [ -n "$cand" ]; then MODEL_CPT="$cand"; SRC_TAG="$seg"; break; fi
    done
  fi
  if [ -z "${MODEL_CPT:-}" ] || [ ! -f "$MODEL_CPT" ]; then
    echo "ERROR: no usable checkpoint for ${RUN_NAME} (task $task) under ${BASE}."
    echo "       train the curriculum first, or set MODEL_CPT=<path> or SRC_N_SEGMENTS/SRC_PREV_SEG."
    exit 1
  fi
  echo "Using checkpoint (src stage seg${SRC_TAG}): $MODEL_CPT"

  for MAX_N_SEGMENTS in "${EVAL_SEGMENTS[@]}"; do
    EXP_PATH="${BASE}/eval_seg${MAX_N_SEGMENTS}_from${SRC_TAG}/run_${N}"
    if [ -f "$EXP_PATH/all_results.json" ]; then echo "done, skip $EXP_PATH"; continue; fi

    echo "EVAL: task $task  src seg${SRC_TAG}  ->  eval at ${MAX_N_SEGMENTS} segments (${MAX_N_SEGMENTS}x${SEGMENT_SIZE} tokens)"
    accelerate launch \
      --main_process_port 0 \
      --num_processes $NP \
      --mixed_precision bf16 \
      --config_file accelerate.yaml \
      run_rmm_on_babilong-v5p7.py \
      --exp_path                    "$EXP_PATH" \
      --per_device_batch_size       $BS \
      --gradient_accumulation_steps 1 \
      --total_batch_size            $(( BS * NP )) \
      --babi_path                   ./data/tasks_1-20_v1-2/en-10k \
      --task_dataset                $TASK_DATASET \
      --noise_dataset               $NOISE_DATASET \
      --segment_size                $SEGMENT_SIZE \
      --max_n_segments              $MAX_N_SEGMENTS \
      --vary_n_segments             False \
      --model_cpt                   "$MODEL_CPT" \
      --validate_only               True \
      --pretrained_model            $PRETRAINED_MODEL \
      --n_head $H \
      --fla_layer $FLA_LAYER --state_size $STATE_SIZE --expand_v $EXPAND_V --conv_kernel $CONV_KERNEL \
      --write_mode $WRITE_MODE --read_mode $READ_MODE \
      --use_parallel_prefill ${PARALLEL_PREFILL:-False} \
      --eval_stream_logits           ${EVAL_STREAM_LOGITS:-True} \
      --max_steps 1 --warmup_steps 0 --eval_steps 1 --logging_steps 1 \
      --metric_for_best_model exact_match \
      --seed $(( N + 42 ))
  done
done
echo "Done"
