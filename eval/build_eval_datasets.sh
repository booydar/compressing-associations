#!/bin/bash
set -e
# Build fixed-noise eval datasets for the noisy-AR sweep.
#
# Env overrides:
#   N_PAIRS_LIST  (default "4 8")  — n_pairs values to build for
#   NB_LIST       (default "4 8 16 32 64 128") — total noise blocks per sample
#   N_VALID       (default 2000)   — number of eval samples per dataset
#   B             (default 7)      — chars per noise block
#   OVERWRITE=1                     — rebuild even if dataset dir exists
#   PYTHON                          — override Python interpreter
#
# Output:
#   data/N{N}-K2V2-V62_NB{NB}-B7_eval{N_VALID}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -z "$PYTHON" ]; then
  for cand in python /home/bulatov/envs/rmt/bin/python /home/bulatov/envs/armt-llm/bin/python /home/bulatov/envs/fla/bin/python /home/bulatov/envs/py311_pt2.6_cu12.4/bin/python; do
    if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
      if "$cand" -c "import datasets" 2>/dev/null; then
        PYTHON="$cand"; break
      fi
    fi
  done
fi
[ -z "$PYTHON" ] && { echo "ERROR: no working python. Activate env or set PYTHON=..."; exit 1; }
echo "using PYTHON=$PYTHON"

B=${B:-7}
N_VALID=${N_VALID:-2000}
OVERWRITE_FLAG=$( [ -n "$OVERWRITE" ] && echo "--overwrite" || echo "" )

for N in ${N_PAIRS_LIST:-4 8}; do
  for NB in ${NB_LIST:-4 8 16 32 64 128}; do
    "$PYTHON" eval/build_eval_dataset.py \
      --n_pairs "$N" \
      --total_noise_blocks "$NB" \
      --noise_block_size "$B" \
      --n_valid "$N_VALID" \
      $OVERWRITE_FLAG
  done
done

echo "Done"
