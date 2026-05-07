import inspect
import torch
import torch.nn as nn
from torch.nn import CrossEntropyLoss

from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions

from fla.models.utils import Cache


class RecurrentMemoryConfig(PretrainedConfig):
    model_type = "rmm"

    def __init__(
        self,
        base_model_name="NousResearch/Llama-3.2-1B",
        base_model_config=None,
        from_pretrained=None,
        fla_layer_name="GatedDeltaNet",
        num_heads=1,
        head_dim=32,
        state_size=None,
        expand_v=2.0,
        conv_size=4,
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
        self.state_size = state_size
        if state_size is not None:
            self.head_dim = state_size // num_heads
        else:
            self.head_dim = head_dim
        self.expand_v = expand_v
        self.conv_size = conv_size
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    def get(self, attr: str, default=None):
        if hasattr(self, attr):
            return getattr(self, attr)
        return default

    def fla_layer_kwargs(self) -> dict:
        return {
            "num_heads": self.num_heads,
            "head_dim": self.head_dim,
            "state_size": self.state_size,
            "expand_v": self.expand_v,
            "conv_size": self.conv_size,
        }


class RecurrentMemoryLayerWrapper(nn.Module):
    """Wraps a transformer layer with a GDN (or other FLA) recurrent layer.

    Order: base_layer → pre-norm → FLA layer → residual add.
    The FLA Cache persists across segments within a sample and is reset
    between samples by calling reset_memory().
    """

    def __init__(self, base_layer: nn.Module, fla_layer: nn.Module):
        super().__init__()
        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.fla_norm = nn.RMSNorm(fla_layer.hidden_size, eps=1e-5)
        # Cache is always a valid Cache object — never None — so that
        # update_layer_cache (called inside fla_layer.forward) always writes state.
        self.cache = Cache()

    def forward(self, hidden_states: torch.Tensor, *args, **kwargs):
        attention_mask = kwargs.get("attention_mask")

        # 1. Base transformer layer (all args/kwargs forwarded unchanged)
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # 2. Pre-norm → FLA layer with persistent cross-segment state
        fla_input = self.fla_norm(hidden_states)
        fla_out = self.fla_layer(
            fla_input,
            attention_mask=attention_mask,
            past_key_values=self.cache,
            use_cache=True,   # always True — ensures final state is stored in cache
        )
        fla_output = fla_out[0]
        # fla_out[2] is the (possibly same) Cache object; re-assign defensively
        # in case the FLA layer ever returns a new Cache instance.
        self.cache = fla_out[2]

        # 3. Residual with learnable gate
        hidden_states = hidden_states + self.gate * fla_output

        # 4. Propagate remaining outputs from the base layer (KV cache, attentions…)
        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    def reset_memory(self):
        """Replace the Cache with a fresh one. Called between samples."""
        self.cache = Cache()


class RecurrentMemoryCell(nn.Module):
    """Replaces each transformer layer in base_model with a RecurrentMemoryLayerWrapper.

    Args:
        base_model: A HuggingFace causal LM (Llama, GPT-2, Pythia, …).
        fla_layer_name: Name of the FLA layer class in fla.layers (e.g. 'GatedDeltaNet').
        **fla_layer_kwargs: Kwargs forwarded to the FLA layer constructor
            (e.g. num_heads, head_dim, expand_v, conv_size).
            'hidden_size' and 'layer_idx' are injected automatically.
    """

    @staticmethod
    def _get_transformer_layers(base_model: nn.Module):
        if hasattr(base_model, "model"):
            return base_model.model.layers
        elif hasattr(base_model, "transformer"):
            return base_model.transformer.h
        else:
            raise AttributeError(f"Cannot find transformer layers in model {type(base_model).__name__}")

    def __init__(self, base_model: nn.Module, fla_layer_name: str = "GatedDeltaNet", **fla_layer_kwargs):
        super().__init__()
        self.model = base_model

        hidden_size = getattr(base_model.config, "n_embd",
                              getattr(base_model.config, "hidden_size", None))
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        transformer_layers = self._get_transformer_layers(base_model)

        # Use GRU-based layer instead of FLA layer
        state_size = fla_layer_kwargs.get("state_size", hidden_size)
        num_heads = fla_layer_kwargs.get("num_heads", 1)
        head_dim = fla_layer_kwargs.get("head_dim", 32)
        
        for i, layer in enumerate(transformer_layers):
            # Create GRU recurrent layer
            gru_layer = GRURecurrentLayer(
                hidden_size=hidden_size,
                state_size=state_size,
                num_heads=num_heads,
                head_dim=head_dim,
            ).to(dtype=model_dtype, device=model_device)

            wrapped = RecurrentMemoryLayerWrapper(
                layer.to(dtype=model_dtype, device=model_device),
                gru_layer,
            )
            transformer_layers[i] = wrapped

    def forward(self, input_ids: torch.Tensor, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)

    def generate(self, input_ids: torch.Tensor, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


class RecurrentMemoryWrapperBase(nn.Module):
    """Iterates over segments, accumulating GDN state across them.

    Mirrors RMCAWrapperBase. The GDN state persists implicitly inside each
    RecurrentMemoryLayerWrapper.cache; no explicit state passing is needed.
    Full BPTT by default (no .detach() truncation).
    """

    def __init__(self, memory_cell: RecurrentMemoryCell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        cell_outputs = []
        for seg_num, segment in enumerate(segments):
            cell_out = self.memory_cell(
                input_ids=segment["input_ids"],
                attention_mask=segment["attention_mask"],
                output_hidden_states=True,
            )
            cell_outputs.append(cell_out)

        labels_mask = None
        if segments and "labels_mask" in segments[0]:
            labels_mask = torch.cat([seg["labels_mask"] for seg in segments], dim=1)

        out = self.process_outputs(
            cell_outputs,
            labels=labels,
            labels_mask=labels_mask,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            **kwargs,
        )
        return out

    def process_outputs(self, cell_outputs, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        if not cell_outputs:
            full_logits = torch.empty(0, 0, 0)
            full_hidden_states = ()
        else:
            full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)
            full_hidden_states = tuple([
                torch.cat(layer_hs, dim=1)
                for layer_hs in zip(*[o.hidden_states for o in cell_outputs])
            ])

        labels = kwargs.get("labels")
        if labels is not None:
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            loss_fct = CrossEntropyLoss()
            labels_mask = kwargs.get("labels_mask")
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous()
                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]

            out["loss"] = loss_fct(flat_logits, flat_labels)
        else:
            out["loss"] = 0

        out["logits"] = full_logits
        if kwargs.get("output_hidden_states"):
            out["hidden_states"] = full_hidden_states

        return out

    def gradient_checkpointing_enable(self, *args, **kwargs):
        self.memory_cell.model.gradient_checkpointing_enable(*args, **kwargs)


class RecurrentMemoryBase(PreTrainedModel):
    config_class = RecurrentMemoryConfig

    def __init__(self, config: RecurrentMemoryConfig, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM

        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            if config.base_model_config is None:
                base_config = AutoConfig.from_pretrained(config.base_model_name)
            else:
                base_config = config.base_model_config
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmm_config = config
        memory_cell = RecurrentMemoryCell(
            base_model,
            fla_layer_name=config.fla_layer_name,
            **config.fla_layer_kwargs(),
        )
        self.rmt = RecurrentMemoryWrapperBase(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id,
        )

    def forward(self, segments=None, labels=None, *args, **kwargs):
        out = self.rmt(segments=segments, labels=labels, *args, **kwargs)
        for layer in RecurrentMemoryCell._get_transformer_layers(self.rmt.memory_cell.model):
            layer.reset_memory()
        return out

    def generate(self, *args, **kwargs):
        return self.rmt.generate(*args, **kwargs)

    def load_state_dict(self, state_dict, strict=True, assign=False):
        try:
            return super().load_state_dict(state_dict, strict, assign)
        except RuntimeError:
            print("Failed to load state dict directly, retrying via rmt sub-module.")
            self.rmt.load_state_dict(state_dict, strict=True, assign=assign)
            print("Success!")

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, config=None, *args, **kwargs):
        from transformers.utils.hub import cached_file, HfHubHTTPError
        import torch

        if config is None:
            config = RecurrentMemoryConfig.from_pretrained(pretrained_model_name_or_path, **kwargs)

        model = cls(config)

        state_dict = None
        try:
            weights_path = cached_file(pretrained_model_name_or_path, "model.safetensors", **kwargs)
            from safetensors.torch import load_file
            state_dict = load_file(weights_path, device="cpu")
        except (OSError, HfHubHTTPError):
            try:
                weights_path = cached_file(pretrained_model_name_or_path, "pytorch_model.bin", **kwargs)
                state_dict = torch.load(weights_path, map_location="cpu")
            except (OSError, HfHubHTTPError):
                print(
                    f"Warning: Could not find weights for {pretrained_model_name_or_path}. "
                    "The model is initialized randomly."
                )

        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)

        return model
