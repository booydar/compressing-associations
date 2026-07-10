#!/bin/bash
set -e
# Prepare data for the babilong RMM runs (prereq for scripts/babilong/*.sh):
#   1) raw bAbI txt tasks -> ./data/tasks_1-20_v1-2/en-10k
#   2) prefetch the pg19 noise corpus into the HF datasets cache (~11GB, one-time)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

PY=${PY:-~/envs/fla/bin/python}

# 1) raw babi tasks
if [ -d ./data/tasks_1-20_v1-2 ]; then
    echo "./data/tasks_1-20_v1-2 already exists, skipping."
else
    # local copy shipped with the babilong-release reference checkout
    BABI_ZIP=${BABI_ZIP:-$HOME/rmt/test-time/tools/rmt-babilong-release/data/tasks_1-20_v1-2.zip}
    if [ -f "$BABI_ZIP" ]; then
        echo "Extracting $BABI_ZIP"
        unzip -q "$BABI_ZIP" -d ./data/
    else
        echo "Downloading bAbI tasks_1-20_v1-2"
        wget -q -O ./data/tasks_1-20_v1-2.tar.gz \
            http://www.thespermwhale.com/jaseweston/babi/tasks_1-20_v1-2.tar.gz
        tar -xzf ./data/tasks_1-20_v1-2.tar.gz -C ./data/
        rm ./data/tasks_1-20_v1-2.tar.gz
    fi
fi

# 2) pg19 noise corpus (HF cache; the runners stream sentences from it)
echo "Prefetching emozilla/pg19 (skips if already cached)"
$PY -c "import datasets; ds = datasets.load_dataset('emozilla/pg19'); print(ds)"
echo "Done"
