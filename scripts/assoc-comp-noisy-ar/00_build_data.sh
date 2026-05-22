#!/bin/bash
set -e
#
# Build Noisy-AR datasets. Two knobs:
#   K = noise blocks per KV pair (env K_LIST, default "2")
#   B = chars per noise block    (env B,      default 7)
#   N = pairs per sample         (env N_PAIRS_LIST, default "4 8")
#   VARY=1                       per-sample blocks drawn uniformly from [1, N*K]
#
# Examples:
#   K_LIST="2"   N_PAIRS_LIST="8" ./00_build_data.sh           # exact 2 blocks/pair
#   K_LIST="8"   N_PAIRS_LIST="8" VARY=1 ./00_build_data.sh    # 1..64 blocks/sample
#   K_LIST="1 2 4" B=7 ./00_build_data.sh                       # 1, 2, 4 blocks/pair sweep
#
# Output:
#   fixed: data/N{N}-K2V2-V62_K{K}-B{B}_1M
#   vary:  data/N{N}-K2V2-V62_K{K}-vary-B{B}_1M

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

if [ -z "$PYTHON" ]; then
  for cand in python /home/bulatov/envs/rmt/bin/python /home/bulatov/envs/armt-llm/bin/python /home/bulatov/envs/fla/bin/python /home/bulatov/envs/py311_pt2.6_cu12.4/bin/python; do
    if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
      if "$cand" -c "import datasets, transformers" 2>/dev/null; then
        PYTHON="$cand"; break
      fi
    fi
  done
fi
[ -z "$PYTHON" ] && { echo "ERROR: no working python. Activate env or set PYTHON=..."; exit 1; }
echo "using PYTHON=$PYTHON"

B=${B:-7}
VARY=${VARY:-}
VARY_FLAG=$( [ -n "$VARY" ] && echo "--vary_noise" || echo "" )
VARY_TAG=$(  [ -n "$VARY" ] && echo "-vary"        || echo "" )
OVERWRITE=${OVERWRITE:-}
OVERWRITE_FLAG=$( [ -n "$OVERWRITE" ] && echo "--overwrite" || echo "" )

for N_PAIRS in ${N_PAIRS_LIST:-4 8}; do
  for K in ${K_LIST:-2}; do
    OUT="./data/N${N_PAIRS}-K2V2-V62_K${K}${VARY_TAG}-B${B}_1M"
    if [ -d "$OUT" ] && [ -z "$OVERWRITE" ]; then
      echo "skip (exists): $OUT"; continue
    fi
    echo ">>> building $OUT  (N=$N_PAIRS, K=$K blocks/pair, B=$B chars/block, VARY=${VARY:-0})"
    "$PYTHON" build_noisy_kv_dataset.py \
      --n_pairs $N_PAIRS \
      --noise_blocks_per_pair $K \
      --noise_block_size $B \
      --n_train 1000000 --n_valid 5000 --seed 142 \
      $VARY_FLAG $OVERWRITE_FLAG
  done
done

echo "Done"
