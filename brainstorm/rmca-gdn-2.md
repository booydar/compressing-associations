
## Assistant

All comments are valid. Let me verify each against the source code:

1. **State not persisted** — `update_layer_cache` (utils.py:178-182): `if past_key_values is not None: return past_key_values.update(...)` else `return None`. **Confirmed.**
2. **use_cache=True** — `gated_deltanet.py` uses it to control `output_final_state`. **Confirmed.**
3. **Missing pre-norm** — `GatedDeltaNetBlock.forward` (modeling_gated_deltanet.py:42-44): `attn_norm` before `self.attn`. **Confirmed.**
4. **attention_mask** — `gated_deltanet.py:225-228`: unpacks padded sequences via `get_unpad_data(attention_mask)`. **Confirmed.**
5. **Short conv state** — Both `conv_state` and `recurrent_state` live in the `Cache` dict. Fixing #1 handles both. **Confirmed.**
6. **layer_idx** — `get_layer_cache` requires `layer_idx` when `past_key_values is not None`. Each FLA layer has its own `layer_idx`. **Confirmed.**

Here's the corrected plan:

---

## Revised Implementation Plan: RecurrentMemoryModel (RMM)

### Architecture

```
Per-layer wrapper (RecurrentMemoryLayerWrapper):
  hidden_states ──► base_transformer_layer ──► hidden_states
                                              │
                                        ┌─────▼──────┐
                                        │  RMSNorm   │  ← pre-norm
                                        └─────┬──────┘
                                              │
                                        ┌─────▼──────┐
                                        │  FLA layer │ (GatedDeltaNet)
                                        │ + residual │  ← past_key_values (Cache)
                                        └─────┬──────┘
                                              │
                                    hidden_states + fla_output
                              Cache (recurrent + conv state, persists across segments)

Segment flow (RecurrentMemoryWrapperBase):
  Segment 1 → Segment 2 → ... → Segment N  (Cache flows through all layers)
  ──────────────────────────────────────────
  At end: reset_memory() → new Cache() for next sample
```

### File 1: `modeling_rmt/huggingface_rmm.py`

**`RecurrentMemoryLayerWrapper`**:
```python
class RecurrentMemoryLayerWrapper(nn.Module):
    def __init__(self, base_layer, fla_layer):
        super().__init__()
        self.base_layer = base_layer
        self.fla_layer = fla_layer  # fla.layers.GatedDeltaNet, etc.
        self.fla_norm = nn.RMSNorm(fla_layer.hidden_size, eps=1e-5)  # pre-norm
        self.cache = Cache()  # FLA Cache, NOT None

    def forward(self, hidden_states, *args, **kwargs):
        attention_mask = kwargs.get('attention_mask')

        # 1. Base transformer layer
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # 2. Pre-norm + FLA layer with explicit state management
        fla_input = self.fla_norm(hidden_states)
        fla_out = self.fla_layer(
            fla_input,
            attention_mask=attention_mask,
            past_key_values=self.cache,
            use_cache=True,  # forced, not deferred
        )
        fla_output = fla_out[0]
        self.cache = fla_out[2]  # updated Cache

        # 3. Residual connection
        hidden_states = hidden_states + fla_output

        # 4. Pass through base layer outputs (cache, attentions)
        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    def reset_memory(self):
        self.cache = Cache()  # fresh Cache, NOT None
```

**`RecurrentMemoryCell`**:
```python
class RecurrentMemoryCell(nn.Module):
    def __init__(self, base_model, fla_layer_name="GatedDeltaNet", **fla_layer_kwargs):
        super().__init__()
        self.model = base_model

        hidden_size = getattr(base_model.config, "n_embd", base_model.config.hidden_size)
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        import inspect, fla.layers
        layer_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(layer_cls.__init__)

        # Build kwargs accepted by this FLA layer
        base_kwargs = {k: v for k, v in fla_layer_kwargs.items()
                       if k in sig.parameters}

        for i, layer in enumerate(self.model.model.layers):
            fla_layer = layer_cls(
                **base_kwargs,
                hidden_size=hidden_size,
                layer_idx=i,  # unique per layer for Cache indexing
            ).to(dtype=model_dtype, device=model_device)

            wrapped = RecurrentMemoryLayerWrapper(
                layer.to(dtype=model_dtype, device=model_device),
                fla_layer,
            )
            self.model.model.layers[i] = wrapped
```

**`RecurrentMemoryWrapperBase`** (same as `RMCAWrapperBase`):
- Iterates segments, calls cell per segment
- **Critical**: `process_outputs` concatenates logits/hidden_states across segments
- **Critical**: `reset_memory()` calls `layer.reset_memory()` for each wrapped layer at end of forward

**`RecurrentMemoryConfig`** + **`RecurrentMemoryBase`**:
```python
class RecurrentMemoryConfig(PretrainedConfig):
    model_type = "rmm"
    def __init__(self,
                 base_model_name="...",
                 base_model_config=None,
                 fla_layer_name="GatedDeltaNet",
                 num_heads=1,
                 head_dim=None,      # derived from state_size
                 expand_v=2,
                 conv_size=4,
                 use_short_conv=True,
                 use_gate=True,
                 **kwargs):

class RecurrentMemoryBase(PreTrainedModel):
    config_class = RecurrentMemoryConfig

    def forward(self, segments, labels=None, **kwargs):
        out = self.rmt(segments=segments, labels=labels, **kwargs)
        # Reset memory at end of forward (mirrors RMCA)
        for layer in self.rmt.memory_cell.model.model.layers:
            layer.reset_memory()
        return out
```

### File 2: `run_rmm_on_kv_retrieval.py`

Based on `run_rmca_on_kv_retrieval-v2.py`:

| Change | Detail |
|--------|--------|
| Import | `modeling_rmt.huggingface_rmm` |
| `--fla_layer` | `"GatedDeltaNet"` (default) |
| `--state_size` | `head_dim` for FLA layer (4/16/32) |
| `--conv_kernel` | `conv_size` in FLA (default 4) |
| `--expand_v` | Value expansion (default 2) |
| `--n_head` | GDN `num_heads` (default 1) |

Model construction:
```python
head_dim = args.state_size // args.n_head
rmm_config = RecurrentMemoryConfig(
    base_model_config=config,
    fla_layer_name=args.fla_layer,
    num_heads=args.n_head,
    head_dim=head_dim,
    expand_v=args.expand_v,
    conv_size=args.conv_kernel,
)
model = RecurrentMemoryBase(rmm_config)
```

### File 3: `scripts/assoc-comp/run_rmm_gdn_on_kv_retrieval-N8.sh`

Same sweep grid as RMCA, with `state_size` = 4/16/32, `conv_kernel` = 4.

---

### Bug Fix Summary

| Bug | Fix |
|-----|-----|
| State not persisted | `Cache()` init in `__init__`, `Cache()` in `reset_memory()` |
| use_cache default | Hardcode `use_cache=True` in wrapper |
| Missing pre-norm | `self.fla_norm = nn.RMSNorm(hidden_size)` before FLA forward |
| Missing attention_mask | Pass `attention_mask` from `kwargs` to FLA layer |
| layer_idx | Each FLA layer gets unique `layer_idx=i` |
| Weight decay on A_log/dt_bias | Sweep already uses `weight_decay=0.0` |
| Reset loop | `RecurrentMemoryBase.forward` calls `layer.reset_memory()` |
| Short conv state | Handled by `Cache()` (stores both `recurrent_state` + `conv_state`) |

---



**Tool: question**

---

## Assistant

Plan is complete and verified against FLA source. All 8 bugs from the review are addressed. Ready to implement three files:

1. `modeling_rmt/huggingface_rmm.py` — `RecurrentMemoryLayerWrapper`, `RecurrentMemoryCell`, `RecurrentMemoryWrapperBase`, `RecurrentMemoryConfig`, `RecurrentMemoryBase`
2. `run_rmm_on_kv_retrieval.py` — training script with FLA layer args
3. `scripts/assoc-comp/run_rmm_gdn_on_kv_retrieval-N8.sh` — sweep with state_size 4/16/32

Proceed with implementation?



**Tool: question**

---

