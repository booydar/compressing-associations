# Noisy-AR eval pipeline

Evaluate a trained noisy-AR checkpoint (GDN / ARMT / RMM v5p4) at a sweep of
out-of-domain noise levels and aggregate the results into the comparison
table.

Layout — all paths relative to `remote/` (the repo root):

```
eval/
  build_eval_dataset.py        # fixed-NB eval-only dataset builder
  build_eval_datasets.sh       # sweep builder (N × NB grid)
  eval_fla.py                  # GDN eval (port of run_fla_on_kv_retrieval-default.py)
  eval_armt.py                 # ARMT eval (port of run_original_armt_on_kv_retrieval-v3-gen.py)
  eval_rmm_v5p4.py             # RMM v5p4 eval (port of run_rmm_on_kv_retrieval-v5p4.py)
  run_eval_sweep.py            # orchestrator: reads run_dir/config.json, loops NB, calls eval
  eval_gdn_noisy.sh            # thin bash wrappers — one per model
  eval_armt_noisy.sh
  eval_rmm_v5p4_noisy.sh
  collect_noisy_eval.py        # aggregator (also importable from a notebook)
  collect_noisy_eval.ipynb     # driver notebook for the aggregator
```

## What it does

Noise grid is **absolute total noise blocks per sample**, independent of
`n_pairs`. Default: `NB ∈ {4, 8, 16, 32, 64, 128}` (each block = 7 chars =
one KV-pair-equivalent). Eval `N_pairs` is auto-detected from the run's
training `config.json` so the model is evaluated at the same `N` it was
trained on.

For each NB level the sweep:
1. Builds `data/N{N}-K2V2-V62_NB{NB}-B7_eval{N_VALID}` if missing
   (fixed noise count, 2000 valid samples by default — no train split is
   used, a 1-sample stub is included only to keep the `DatasetDict` shape
   expected by the trainers).
2. Runs the model-specific eval script with the same model hyperparams as
   the training run (forwarded from `<run_dir>/config.json`).
3. Writes per-sample predictions and aggregate metrics under:

   ```
   <run_dir>/eval_noisy/NB{NB}/
     predictions.jsonl   # {input, prediction, label, exact_match} per sample
     metrics.json        # {eval_exact_match, eval_token_accuracy, ...}
   ```

Re-runs are skipped if `metrics.json` already exists; pass `FORCE=1` to
override.

> Note on `predictions.jsonl`: for ARMT/RMM the model's `main_input_name`
> is `labels`, so the `input` field reflects the labels tensor (target
> chars only). The `prediction`, `label`, and `exact_match` fields are
> accurate. For GDN the `input` field is the full input sequence.

## Usage

```bash
# 0) (optional) pre-build all eval datasets in one go
bash eval/build_eval_datasets.sh

# 1) evaluate a single run
bash eval/eval_gdn_noisy.sh \
  runs-noisy-ar/N4-K2V2-V62_K1-vary-B7_1M/gdn_gated_delta_net_L4H4D128_ss32_ck4_lr1e-03_bs64/run_1

bash eval/eval_armt_noisy.sh \
  runs-noisy-ar/N4-K2V2-V62_K1-vary-B7_1M/armt_llama_L4H4D128_mem4d32_lr3e-04_tps7_bs64/run_1

bash eval/eval_rmm_v5p4_noisy.sh \
  runs-noisy-ar/N4-K2V2-V62_K1-vary-B7_1M/rmmv5p4_GatedDeltaNet_llama_L4H4D128_ss32_M4_unpool_pool_lr3e-04_bs64_pps1_tps7/run_1

# 2) aggregate results into the table
python eval/collect_noisy_eval.py \
  --runs_root runs-noisy-ar \
  --out_csv_wide eval/noisy_eval_table.csv \
  --out_csv_long eval/noisy_eval_long.csv

# or open eval/collect_noisy_eval.ipynb
```

## Knobs (env vars on the bash wrappers)

| var       | default                  | purpose                                  |
|-----------|--------------------------|------------------------------------------|
| `NB_LIST` | `4,8,16,32,64,128`       | comma-sep noise-block counts             |
| `N_VALID` | `2000`                   | eval samples per NB level                |
| `BS`      | `32`                     | per-device eval batch size               |
| `PYTHON`  | `python`                 | python interpreter                       |
| `FORCE=1` | unset                    | re-run noise levels already evaluated    |

Drop to `BS=8` or `BS=16` if NB=128 OOMs on a 2×H100 (long contexts +
many ARMT/RMM segments).

## Sweeping many runs

```bash
for d in runs-noisy-ar/*/gdn_*/run_*; do
  bash eval/eval_gdn_noisy.sh "$d"
done
for d in runs-noisy-ar/*/armt_*/run_*; do
  bash eval/eval_armt_noisy.sh "$d"
done
for d in runs-noisy-ar/*/rmmv5p4_*/run_*; do
  bash eval/eval_rmm_v5p4_noisy.sh "$d"
done
```
