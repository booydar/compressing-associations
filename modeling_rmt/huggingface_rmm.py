"""Recurrent Memory Model (RMM): base transformer + FLA layer per layer.

Architectural difference from RMCA:
  - No memory tokens. A single recurrent state (FLA Cache) is maintained per layer.
  - Each wrapped layer: base_transformer -> RMSNorm -> FLA_layer (residual).
  - Recurrent state persists across segments, resets at end of forward pass.
"""

import inspect
import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions

# Import FLA Cache — version-agnostic (FLACache or LegacyFLACache)
from fla.models.utils import Cache as FLACache


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class RecurrentMemoryConfig(PretrainedConfig):
    model_type = "rmm"

    def __init__(
        self,
        base_model_name="gpt2",
        base_model_config=None,
        from_pretrained=None,
        fla_layer_name="GatedDeltaNet",
        num_heads=1,
        head_dim=None,
        expand_v=2,
        conv_size=4,
        use_short_conv=True,
        use_gate=True,
        max_n_segments=10,
        think_token_id=None,
        answer_token_id=None,
        bos_token_id=None,
        eos_token_id=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.base_model_name = base_model_name
        self.base_model_config = base_model_config
        self.from_pretrained = from_pretrained
        self.fla_layer_name = fla_layer_name
        self.num_heads = num_heads
        self.head_dim = head_dim
        self.expand_v = expand_v
        self.conv_size = conv_size
        self.use_short_conv = use_short_conv
        self.use_gate = use_gate
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id


# ---------------------------------------------------------------------------
# Per-layer wrapper: base transformer + FLA layer
# ---------------------------------------------------------------------------

class RecurrentMemoryLayerWrapper(nn.Module):
    """Wraps a transformer decoder layer with an FLA layer (e.g. GatedDeltaNet).

    Forward path:
        hidden  -> base_transformer_layer -> hidden
                            |
                     RMSNorm (pre-norm)
                            |
                      FLA_layer (with recurrent state)
                             |
                      hidden + fla_output  (residual)
    """

    def __init__(self, base_layer, fla_layer):
        super().__init__()
        self.base_layer = base_layer
        self.fla_layer = fla_layer

        hidden_size = fla_layer.hidden_size
        self.fla_norm = nn.RMSNorm(hidden_size, eps=1e-5)
        # FLACache persists recurrent_state + conv_state across segments.
        # Must NOT be None — update_layer_cache skips when past_key_values=None.
        self._cache = FLACache()

    # ---- public helpers ----

    def reset_memory(self):
        # Fresh cache for next sample; recurrent state is cleared.
        self._cache = FLACache()

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, value):
        self._cache = value

    # ---- forward ----

    def forward(self, hidden_states, *args, **kwargs):
        attention_mask = kwargs.get("attention_mask")

        # 1) Base transformer layer
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else hidden_states

        # 2) Pre-norm -> FLA layer -> residual
        #    use_cache=True is forced to ensure kernel outputs final state.
        fla_input = self.fla_norm(hidden_states)
        fla_out = self.fla_layer(
            fla_input,
            attention_mask=attention_mask,
            past_key_values=self._cache,
            use_cache=True,
        )
        fla_output = fla_out[0]
        self._cache = fla_out[2]

        hidden_states = hidden_states + fla_output

        # 3) Pass through base layer auxiliary outputs (cache, attentions)
        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states


# ---------------------------------------------------------------------------
# Cell: wraps all base model layers
# ---------------------------------------------------------------------------

class RecurrentMemoryCell(nn.Module):
    """Replaces each transformer decoder layer with RecurrentMemoryLayerWrapper."""

    def __init__(self, base_model, fla_layer_name="GatedDeltaNet", **fla_layer_kwargs):
        super().__init__()
        self.model = base_model
        self.fla_layer_name = fla_layer_name

        hidden_size = getattr(
            base_model.config, "n_embd", base_model.config.hidden_size
        )
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        # Resolve FLA layer class
        import fla.layers
        layer_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(layer_cls.__init__)

        # Only pass kwargs that the FLA layer accepts
        base_kwargs = {
            k: v for k, v in fla_layer_kwargs.items()
            if k in sig.parameters
        }
        base_kwargs.setdefault("hidden_size", hidden_size)

        for i, layer in enumerate(self.model.model.layers):
            fla_layer = layer_cls(
                **base_kwargs,
                layer_idx=i,
            ).to(dtype=model_dtype, device=model_device)

            wrapped = RecurrentMemoryLayerWrapper(
                layer.to(dtype=model_dtype, device=model_device),
                fla_layer,
            )
            self.model.model.layers[i] = wrapped

    def forward(self, input_ids, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)

    def generate(self, input_ids, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


# ---------------------------------------------------------------------------
# Wrapper: segment processing + recurrent state management
# ---------------------------------------------------------------------------

class RecurrentMemoryWrapperBase(nn.Module):
    """Processes segments sequentially; recurrent state flows across segments."""

    def __init__(self, memory_cell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(
        self,
        segments,
        labels=None,
        output_attentions=None,
        output_hidden_states=None,
        *args,
        **kwargs,
    ):
        cell_outputs = []
        for segment in segments:
            cell_out = self.memory_cell(
                input_ids=segment["input_ids"],
                attention_mask=segment["attention_mask"],
                output_hidden_states=True,
            )
            cell_outputs.append(cell_out)

        # Extract labels_mask from segments if available
        labels_mask = None
        if "labels_mask" in segments[0]:
            labels_mask = torch.cat(
                [seg["labels_mask"] for seg in segments], dim=1
            )

        return self.process_outputs(
            cell_outputs,
            labels=labels,
            labels_mask=labels_mask,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            **kwargs,
        )

    def process_outputs(self, cell_outputs, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)
        full_hidden_states = tuple(
            torch.cat(layer_hs, dim=1)
            for layer_hs in zip(*[o.hidden_states for o in cell_outputs])
        )

        labels = kwargs.get("labels")
        if labels is not None:
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            labels_mask = kwargs.get("labels_mask")
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous()
                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]

            out["loss"] = CrossEntropyLoss()(flat_logits, flat_labels)
        else:
            out["loss"] = 0

        out["logits"] = full_logits

        if kwargs.get("output_hidden_states"):
            out["hidden_states"] = full_hidden_states

        return out


# ---------------------------------------------------------------------------
# HuggingFace-compatible model
# ---------------------------------------------------------------------------

class RecurrentMemoryBase(PreTrainedModel):
    config_class = RecurrentMemoryConfig

    def __init__(self, config: RecurrentMemoryConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM

        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(
                config.from_pretrained
            )
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        fla_kwargs = {}
        if config.num_heads is not None:
            fla_kwargs["num_heads"] = config.num_heads
        if config.head_dim is not None:
            fla_kwargs["head_dim"] = config.head_dim
        if config.expand_v is not None:
            fla_kwargs["expand_v"] = config.expand_v
        if config.conv_size is not None:
            fla_kwargs["conv_size"] = config.conv_size
        if config.use_short_conv is not None:
            fla_kwargs["use_short_conv"] = config.use_short_conv
        if config.use_gate is not None:
            fla_kwargs["use_gate"] = config.use_gate

        memory_cell = RecurrentMemoryCell(
            base_model,
            fla_layer_name=config.fla_layer_name,
            **fla_kwargs,
        )
        self.rmt = RecurrentMemoryWrapperBase(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id,
        )

    def forward(self, segments, labels=None, *args, **kwargs):
        out = self.rmt(segments=segments, labels=labels, *args, **kwargs)
        for layer in self.rmt.memory_cell.model.model.layers:
            layer.reset_memory()
        return out

    def generate(self, *args, **kwargs):
        return self.rmt.generate(*args, **kwargs)

    def load_state_dict(self, state_dict, strict=True, assign=False):
        try:
            return super().load_state_dict(state_dict, strict, assign)
        except RuntimeError:
            print("Failed to load state, retrying with RMT loader.")
            self.rmt.load_state_dict(state_dict, strict=True, assign=assign)
            print("Success!")

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, config=None, *args, **kwargs):
        from transformers.utils.hub import cached_file, HfHubHTTPError

        if config is None:
            config = RecurrentMemoryConfig.from_pretrained(
                pretrained_model_name_or_path, **kwargs
            )

        model = cls(config)

        state_dict = None
        try:
            weights_path = cached_file(
                pretrained_model_name_or_path, "model.safetensors", **kwargs
            )
            from safetensors.torch import load_file
            state_dict = load_file(weights_path, device="cpu")
        except (OSError, HfHubHTTPError):
            try:
                weights_path = cached_file(
                    pretrained_model_name_or_path, "pytorch_model.bin", **kwargs
                )
                state_dict = torch.load(weights_path, map_location="cpu")
            except (OSError, HfHubHTTPError):
                print(
                    f"Warning: Could not find weights for "
                    f"{pretrained_model_name_or_path}. "
                    f"The model is initialized randomly."
                )

        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)

        return model
