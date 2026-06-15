#!/bin/bash
set -e
# Download babilong qaX_0k into ./data/ (prerequisite for the babi RMM runs).
# Mirrors gradmem/scripts/download_babi.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PY=${PY:-~/envs/fla/bin/python}
DATASETS=("babilong_qa1_0k" "babilong_qa2_0k" "babilong_qa3_0k" "babilong_qa4_0k" "babilong_qa5_0k")

for DATASET in "${DATASETS[@]}"; do
    if [ -d "./data/${DATASET}" ]; then
        echo "./data/${DATASET} already exists, skipping."
        continue
    fi
    echo "Downloading $DATASET"
    $PY -c "import datasets; datasets.load_dataset('yurakuratov/${DATASET}').save_to_disk('./data/${DATASET}')"
done
echo "Done"
