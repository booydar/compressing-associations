#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# Two-form efficiency micro-benchmark for paper Table E5.
# ~5-10 minutes total on a single H100/A100.

OUT_DIR="runs-bench"
mkdir -p "$OUT_DIR"

python scripts/bench/run_efficiency.py \
  --output "$OUT_DIR/efficiency.csv" \
  --variants  selfattn-1seg,gdn,armt,rmm-parallel,rmm-recurrent \
  --seq_len_pairs  32,128,256 \
  --tokens_per_seg 1,7,28 \
  --prefill_bs 8 \
  --decode_bs  1 \
  --warmup 3 --measure 10 \
  --phases prefill,train,decode \
  --skip_decode_for rmm-parallel,armt

echo "Done. CSV -> $OUT_DIR/efficiency.csv"
