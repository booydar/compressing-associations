# Repository Conventions
(Reference document for the LLM agents — do not delete)

## Directory Layout
```
autoresearch/
  modeling_rmt/
    huggingface_rmca_v2.py   — original RMCA (do not modify)
    huggingface_rmca_v3.py   — agent-editable copy (modified each iteration)
  run_rmca_on_kv_retrieval-v2.py   — original trainer (do not modify)
  run_rmca_on_kv_retrieval-v3.py   — trainer that imports from v3
  scripts/
    run_autoresearch_exp.sh  — short-run launcher for autoresearch
    test_rmca.sh             — quick smoke test
  data/
    N2-K2V2-V62_1M/          — N=2 dataset
    N4-K2V2-V62_1M/          — N=4 dataset (generated on first use)
  runs-autoresearch/         — raw experiment outputs
    n2/iter_000_baseline/
    n2/iter_001/
    ...
  .autoresearch/             — autoresearch infrastructure (this folder)
```

## Model File: huggingface_rmca_v3.py

### Key Classes
- `RMCAConfig(PretrainedConfig)` — model config, inherits from HF
- `LlamaCrossAttention(nn.Module)` — cross-attention module (Q from one source, K/V from another)
- `MemoryAugmentedLayer(nn.Module)` — wraps a single transformer layer with memory R/W
- `RMCACell(nn.Module)` — wraps the full model, replaces each layer with MemoryAugmentedLayer
- `RMCAWrapperBase(nn.Module)` — processes segments, calls RMCACell per segment
- `RMCABase(PreTrainedModel)` — top-level HF model, resets memory after each forward

### Data Flow (per sample, N=2)
1. Context segment (2 KV pairs) → all MemoryAugmentedLayers update their memory states
2. Query+target segment → layers read from memory, compute logits
3. Loss computed only on target tokens
4. Memory reset in `RMCABase.forward()` after each call

### MemoryAugmentedLayer.forward() detail
```
memory = layer.memory_state   # (batch, num_mem_tokens, hidden_size)
# read
read_residual = memory_read(input_norm, memory_norm)   # hidden updates from memory
hidden_states = hidden_states + read_residual
# write
write_residual = memory_write(memory_norm, input_norm)  # memory updates from input
memory = memory + write_residual
# base layer
output = base_layer(hidden_states)
```

### Config Parameters (set by trainer CLI)
| arg          | meaning                              | default |
|--------------|--------------------------------------|---------|
| n_layer      | number of transformer layers         | 4       |
| n_head       | number of attention heads            | 4       |
| n_embd       | hidden dimension                     | 128     |
| n_mem_tokens | number of memory tokens per layer    | 8       |
| base_model   | backbone type: llama / gpt2 / pythia | llama   |
| n_keys       | key length in characters             | 2       |
| n_values     | value length in characters           | 2       |
| n_pairs      | total KV pairs = N-level             | 2       |

### Evaluation
- Primary metric: `eval_exact_match` — fraction of samples where all value tokens are correct
- Secondary: `eval_token_accuracy` — token-level accuracy on value tokens only
- Written to `{exp_path}/all_results.json` by `trainer.save_metrics(split='all', ...)`

## What NOT to Change
- Do not modify `RMCABase.from_pretrained()` (HF loading infrastructure)
- Do not change class names or constructor signatures of `RMCABase`, `RMCAConfig`
  (the trainer instantiates these by name)
- Do not add new CLI arguments without also updating `run_rmca_on_kv_retrieval-v3.py`

## Naming Conventions
- New helper classes: PascalCase, suffix with purpose (e.g. `MemoryGate`, `CrossLayerSkip`)
- New nn.Module attributes in MemoryAugmentedLayer: snake_case
- Buffer names: `initial_<thing>_state` pattern

## Hyperparameter Sweeps (experiment_config.yaml)

To sweep a hyperparameter, use the `values:` format with a `default`:

```yaml
learning_rate:
  values: [0.0001, 0.0005, 0.001, 0.005, 0.01]
  default: 0.01
```

Supported sweep parameters (ONE sweep per run):
- `learning_rate` - learning rate sweep
- `n_mem_tokens` - memory token count sweep

The sweep runs all values as separate sub-experiments and uses the best EM across all values.
Each sub-experiment is saved in a subfolder (e.g., `iter_045_lr_0_0`, `iter_045_lr_0_1`, etc.).

Example for learning rate sweep:
```yaml
learning_rate:
  values: [0.0001, 0.001, 0.01]
  default: 0.01
```

Example for memory token sweep:
```yaml
n_mem_tokens:
  values: [8, 16, 32, 64]
  default: 32
```
