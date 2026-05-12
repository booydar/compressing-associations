# Repository Conventions
(Reference document for the LLM agents — do not delete)

## Directory Layout
```
compressing-associations-gdn/
  modeling_rmt/
    huggingface_rmm_v5.py    — agent-editable model file (modified each iteration)
  run_rmm_on_kv_retrieval-v5.py  — training script (do not modify)
  scripts/
    run_autoresearch_exp.sh  — short-run launcher for autoresearch (v5-aware)
    assoc-comp-rmm/run_rmm_v5_on_kv_retrieval-ca.sh  — full multi-seed sweep (manual)
  data/
    N2-K2V2-V62_1M/          — N=2 dataset
    N4-K2V2-V62_1M/          — N=4 dataset (generated on first use)
  runs/autoresearch/
    stream_0/
      n2/iter_000_baseline/
      n2/iter_001/
      ...
  .autoresearch/             — autoresearch infrastructure (this folder)
```

## Model File: huggingface_rmm_v5.py

### Key Classes
- `RecurrentMemoryConfig(PretrainedConfig)` — model config, inherits from HF
- `MemoryWriter` / `MemoryReader` — v5 write/read paths (identity / pool+cross-attn / unpool, etc.)
- `RecurrentMemoryLayerWrapper(nn.Module)` — wraps one transformer layer with an FLA recurrent layer (residual)
- `RecurrentMemoryCell(nn.Module)` — replaces all transformer decoder layers with RecurrentMemoryLayerWrapper
- `RecurrentMemoryWrapperBase(nn.Module)` — processes segments sequentially, recurrent state flows across segments
- `RecurrentMemoryBase(PreTrainedModel)` — top-level HF model, resets recurrent memory after each forward

### Architecture (per layer)
```
hidden → base_transformer_layer → hidden
                 |
           RMSNorm (pre-norm)
                 |
           FLA_layer (GatedDeltaNet or similar, with recurrent Cache)
                 |
         hidden + fla_output   (residual)
```
Recurrent state (`FLACache`) persists across segments within one sample and resets via `reset_memory()`.

### Config Parameters (set by trainer CLI)
| arg          | meaning                              | default       |
|--------------|--------------------------------------|---------------|
| n_layer      | number of transformer layers         | 4             |
| n_head       | number of FLA heads                  | 1             |
| n_embd       | hidden dimension                     | 128           |
| fla_layer    | FLA layer class name                 | GatedDeltaNet |
| state_size   | num_heads × head_dim                 | 32            |
| expand_v     | value expansion factor in FLA        | 2.0           |
| conv_kernel  | short-conv kernel size               | 4             |
| base_model   | backbone type: gpt2 / llama / pythia | gpt2          |
| n_keys       | key length in characters             | 2             |
| n_values     | value length in characters           | 2             |
| n_pairs      | total KV pairs = N-level             | 2             |
| tokens_per_segment | context chunk size in tokens (v5) | derived from pairs_per_segment × (n_keys + n_values + 4) in `run_autoresearch_exp.sh` |
| num_memory_vectors | memory bank width M (v5)        | 1             |
| write_mode   | v5 memory write path               | cross_attn    |
| read_mode    | v5 memory read path                | cross_attn    |

### Evaluation
- Primary metric: `eval_exact_match` — fraction of samples where all value tokens are correct
- Secondary: `eval_token_accuracy` — token-level accuracy on value tokens only
- Written to `{exp_path}/all_results.json` by `trainer.save_metrics(split='all', ...)`

## What NOT to Change
- Do not modify `RecurrentMemoryBase.from_pretrained()` (HF loading infrastructure)
- Do not change class names or constructor signatures of `RecurrentMemoryBase`, `RecurrentMemoryConfig`
  (the trainer instantiates these by name)
- Do not add new CLI arguments without also updating `run_rmm_on_kv_retrieval-v5.py` and `scripts/run_autoresearch_exp.sh`

## Naming Conventions
- New helper classes: PascalCase, suffix with purpose (e.g. `RecurrentGate`, `LayerSkip`)
- New nn.Module attributes: snake_case
- Buffer names: `initial_<thing>_state` pattern

## Hyperparameter Sweeps (experiment_config.yaml)

To sweep a hyperparameter, use the `values:` format with a `default`:

```yaml
learning_rate:
  values: [0.0001, 0.0005, 0.001, 0.005, 0.01]
  default: 0.001
```

Supported sweep parameters (ONE sweep per run):
- Any parameter in the config: `learning_rate`, `state_size`, `n_layer`, `n_head`, `n_embd`, `batch_size`, `warmup_steps`, `max_steps`, `expand_v`, etc.

The sweep runs all values as separate sub-experiments and uses the best EM across all values.
Each sub-experiment is saved in a subfolder (e.g., `iter_045_lr_0_0`, `iter_045_lr_0_1`, etc.).
