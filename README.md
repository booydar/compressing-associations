# Compressing Associations (segment-level memory on GDN)

Small experiments on key--value retrieval: compress context segments into a fixed recurrent state (Gated DeltaNet), then answer queries. Older scripts train GPT-style LMs and test-time `[mem]` gradient updates.


## Intro
Large-context transformers pay a **quadratic cost** every time they reread long prompts.

Our goal is to compress each context **segment** into a few memory vectors, update a **GDN state** across segments, then read back for the query—without keeping the full token history in the recurrent path.

### How it works (RMM)

| Phase | What happens | Per segment | Input |
|-------|--------------|-------------|--------|
| **Write** | Segment tokens → `M` write vectors (`pool` / `cross_attn` / `identity`) → rank-1 updates to GDN state | 1 | segment tokens |
| **Read** | State + write cache → `unpool` / `cross_attn` / `identity` → local LM on query segment | 1 | query segment |

`tokens_per_segment` (`tps`) sets segment length; `num_memory_vectors` (`M`) is write rank. **`identity`** ≈ token-level GDN (one update per token). See `knowledge/RESEARCH_DIRECTION.md` for paper framing.


## Prerequisites

* Python 3.11
* [conda](https://docs.conda.io/en/latest/) for environment management

Create an environment using the provided YAML file:

```bash
conda env create -f conda_env.yaml
conda activate /home/jovyan/kuratov/envs/py311_pt2.6_cu12.4  # or the path printed by conda
```

Accelerate is configured via `accelerate.yaml`. The default configuration uses BF16 precision and a single process.

## Dataset generation

Datasets consist of sequences containing random text segments with embedded `!key:value!` pairs. The last segment queries one of the previous keys (e.g. `?!K:`) and the model must output the corresponding value.

Use `kv_dataset_utils.generate_sequence` to create samples and dump with Hugging Face `datasets`. Data lives under `./data/<DATASET_NAME>`, e.g. `N4-K2V2-V62_1M` (4 pairs, key len 2, value len 2).

## Training

**Current line:** RMM over GDN — trainers `run_rmm_on_kv_retrieval-v5.py`, `v5p1`, `v5p2`, `v6` (models in `modeling_rmt/huggingface_rmm_v5*.py`). Example launchers: `scripts/assoc-comp-rmm/` (e.g. `run_rmm_v5_on_kv_retrieval-id.sh`, `run_rmm_v5p2_on_kv_retrieval-pool-7tps.sh`, `run_baseline_rmt_armt.sh`).

**Baselines:** `run_original_armt_on_kv_retrieval.py`, `run_original_rmt_on_kv_retrieval-v3-gen.py`, `run_fla_on_kv_retrieval-default.py`.

**Legacy:** `run_gpt2_on_kv_retrieval.py`, `run_gradmemgpt_on_kv_retrieval.py` (test-time `[mem]` updates; gradient modes `none` / `first` / `second`).

Launch via `accelerate` from the repo root:

```bash
accelerate launch --config_file accelerate.yaml \
  run_rmm_on_kv_retrieval-v5p2.py \
  --exp_path ./runs-rmmv5p2/N4-K2V2-V62_1M/my_run/run_1 \
  --per_device_batch_size 64 \
  --data_path ./data/N4-K2V2-V62_1M \
  --tokenizer_path ./tokenizers/kv_alphabet_62/ \
  --num_memory_vectors 4 --write_mode pool --read_mode unpool \
  --tokens_per_segment 7 --n_pairs 4
```

Or run a sweep script:

```bash
bash scripts/assoc-comp-rmm/run_rmm_v5_on_kv_retrieval-pool.sh
```

Checkpoints and metrics go to `--exp_path`; aggregate with `notebooks/collect_results_rmmv5.ipynb`.
