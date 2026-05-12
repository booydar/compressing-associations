import inspect
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions

import fla.layers
from fla.models.utils import Cache


class LlamaCrossAttention(nn.Module):
    """Cross-attention: Q from from_states, K/V from to_states. No causal mask, no RoPE."""

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        kv_hidden_size: int | None = None,
        head_dim: int | None = None,
        dropout: float = 0.0,
        bias: bool = False,
        out_hidden_size: int | None = None,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = head_dim if head_dim is not None else hidden_size // num_heads
        self.scaling = self.head_dim ** -0.5
        self.attention_dropout = dropout
        kv_hidden_size = kv_hidden_size or hidden_size

        self.q_proj = nn.Linear(hidden_size, num_heads * self.head_dim, bias=bias)
        self.k_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.v_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.o_proj = nn.Linear(num_heads * self.head_dim, out_hidden_size or hidden_size, bias=bias)

    def forward(
        self,
        from_states: torch.Tensor,    # (B, Q_len, hidden_size)
        to_states: torch.Tensor,      # (B, K_len, kv_hidden_size)
        attention_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        B, Q_len, _ = from_states.shape
        K_len = to_states.shape[1]

        query_states = self.q_proj(from_states).view(B, Q_len, self.num_heads, self.head_dim).transpose(1, 2)
        key_states   = self.k_proj(to_states).view(B, K_len, self.num_heads, self.head_dim).transpose(1, 2)
        value_states = self.v_proj(to_states).view(B, K_len, self.num_heads, self.head_dim).transpose(1, 2)

        attn_weights = torch.matmul(query_states, key_states.transpose(-2, -1)) * self.scaling
        if attention_mask is not None:
            attn_weights = attn_weights + attention_mask
        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(query_states.dtype)
        if self.training and self.attention_dropout > 0:
            attn_weights = F.dropout(attn_weights, p=self.attention_dropout)

        attn_output = torch.matmul(attn_weights, value_states)
        attn_output = attn_output.transpose(1, 2).reshape(B, Q_len, -1).contiguous()
        return self.o_proj(attn_output), attn_weights


class WriteCompressor(nn.Module):
    """Compresses T segment tokens into M write vectors via attention.

    mode='pool':
        M learnable query vectors (no Q projection) attend to K/V from tokens.
        Minimal parameters, closest to simple pooling.

    mode='cross_attn':
        M learnable query vectors with Q/K/V projections and an output projection.
        Queries are per-layer trainable parameters; in future they can be derived
        from the GDN state matrix.

    write_value_dim:
        Output dimension of write vectors. Can be > hidden_size to give the GDN
        richer per-step inputs without changing the model's hidden dimension.
    """

    def __init__(
        self,
        hidden_size: int,
        num_write_vectors: int,
        mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        bias: bool = False,
    ):
        super().__init__()
        if mode not in ('pool', 'cross_attn'):
            raise ValueError(f"mode must be 'pool' or 'cross_attn', got '{mode}'")

        self.mode = mode
        self.num_write_vectors = num_write_vectors
        self.write_value_dim = write_value_dim or hidden_size
        self.scaling = hidden_size ** -0.5

        # Trainable query vectors — one set per layer (per WriteCompressor instance)
        self.write_queries = nn.Parameter(torch.zeros(num_write_vectors, hidden_size))
        nn.init.normal_(self.write_queries, std=0.02)

        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
        self.v_proj = nn.Linear(hidden_size, self.write_value_dim, bias=bias)

        if mode == 'cross_attn':
            self.q_proj  = nn.Linear(hidden_size, hidden_size, bias=bias)
            self.out_proj = nn.Linear(self.write_value_dim, self.write_value_dim, bias=bias)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            hidden_states: (B, T, hidden_size)
        Returns:
            write_vecs:    (B, M, write_value_dim)
        """
        B = hidden_states.shape[0]

        queries = self.write_queries.unsqueeze(0).expand(B, -1, -1)   # (B, M, d)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)

        k = self.k_proj(hidden_states)   # (B, T, d)
        v = self.v_proj(hidden_states)   # (B, T, write_value_dim)

        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling   # (B, M, T)
        attn = F.softmax(attn, dim=-1)
        write_vecs = torch.matmul(attn, v)   # (B, M, write_value_dim)

        if self.mode == 'cross_attn':
            write_vecs = self.out_proj(write_vecs)

        return write_vecs


class RecurrentMemoryLayerWrapper(nn.Module):
    """Wraps a transformer layer with structured GDN-based segment-level write memory.

    Each segment:
      1. READ  – cross-attend current tokens to last segment's M write outputs (dim d).
                 Skipped on the first segment (no previous write memory).
      2. ATTN  – base transformer layer.
      3. WRITE – compress T tokens -> M write vectors (dim write_value_dim) via WriteCompressor,
                 pass through GDN (hidden_size=write_value_dim) to update recurrent state,
                 project GDN output to d and store for next segment's READ.

    Setting num_write_vectors=T and mode='pool' with write_value_dim=d approaches
    the v2 token-by-token update (modulo the learned pooling projections).
    Reducing M < T introduces true segment-level compression before writing.
    """

    def __init__(
        self,
        base_layer: nn.Module,
        fla_layer: nn.Module,
        model_hidden_size: int,
        num_write_vectors: int = 1,
        write_mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        num_read_heads: int = 1,
    ):
        super().__init__()
        self.base_layer = base_layer
        self.fla_layer = fla_layer   # GDN with hidden_size = write_value_dim

        write_value_dim = write_value_dim or model_hidden_size

        self.write_compressor = WriteCompressor(
            hidden_size=model_hidden_size,
            num_write_vectors=num_write_vectors,
            mode=write_mode,
            write_value_dim=write_value_dim,
        )
        self.write_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)

        # READ: tokens (d) attend to previous write outputs (d)
        self.read_cross_attn = LlamaCrossAttention(
            hidden_size=model_hidden_size,
            num_heads=num_read_heads,
        )
        self.read_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)

        # Project GDN output (write_value_dim) -> model_hidden_size for next READ
        if write_value_dim != model_hidden_size:
            self.write_out_proj = nn.Linear(write_value_dim, model_hidden_size, bias=False)
        else:
            self.write_out_proj = None

        self.cache = Cache()
        self.last_write_output: torch.Tensor | None = None   # (B, M, d)

    def forward(self, hidden_states: torch.Tensor, *args, **kwargs):
        # 1. READ: enrich tokens from previous segment's write memory
        if self.last_write_output is not None:
            read_input = self.read_norm(hidden_states)
            read_output, _ = self.read_cross_attn(
                from_states=read_input,
                to_states=self.last_write_output,
            )
            hidden_states = hidden_states + read_output

        # 2. Base transformer layer
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # 3. WRITE: compress segment -> M write vectors -> GDN state update
        write_input = self.write_norm(hidden_states)
        write_vecs = self.write_compressor(write_input)   # (B, M, write_value_dim)

        fla_out = self.fla_layer(
            write_vecs,
            attention_mask=None,   # write vectors have no padding
            past_key_values=self.cache,
            use_cache=True,
        )
        fla_write_output = fla_out[0]   # (B, M, write_value_dim)
        self.cache = fla_out[2]

 q       # Project to model dim and store for next segment's read
        if self.write_out_proj is not None:
            write_output_d = self.write_out_proj(fla_write_output)
        else:
            write_output_d = fla_write_output
        self.last_write_output = write_output_d   # (B, M, d)

        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    def reset_memory(self):
        self.cache = Cache()
        self.last_write_output = None


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
        expand_v=2.0,
        conv_size=4,
        # Write path
        num_write_vectors=1,
        write_mode='cross_attn',    # 'pool' or 'cross_attn'
        write_value_dim=None,       # None = same as model hidden_size
        num_read_heads=1,
        # Misc
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
        self.num_write_vectors = num_write_vectors
        self.write_mode = write_mode
        self.write_value_dim = write_value_dim
        self.num_read_heads = num_read_heads
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    def get(self, attr: str, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self) -> dict:
        return {
            "num_heads": self.num_heads,
            "head_dim": self.head_dim,
            "expand_v": self.expand_v,
            "conv_size": self.conv_size,
        }


class RecurrentMemoryCell(nn.Module):
    """Replaces each transformer layer with a RecurrentMemoryLayerWrapper.

    GDN hidden_size = write_value_dim (defaults to model hidden_size).
    Each wrapper owns its own Cache so layer_idx=0 is used throughout.
    """

    @staticmethod
    def _get_transformer_layers(base_model: nn.Module):
        if hasattr(base_model, "model"):
            return base_model.model.layers
        elif hasattr(base_model, "transformer"):
            return base_model.transformer.h
        else:
            raise AttributeError(f"Cannot find transformer layers in {type(base_model).__name__}")

    def __init__(
        self,
        base_model: nn.Module,
        fla_layer_name: str = "GatedDeltaNet",
        num_write_vectors: int = 1,
        write_mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        num_read_heads: int = 1,
        **fla_layer_kwargs,
    ):
        super().__init__()
        self.model = base_model

        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        gdn_hidden_size = write_value_dim or model_hidden_size
        model_dtype  = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        layer_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(layer_cls.__init__)
        excluded = {"self", "hidden_size", "layer_idx"}
        filtered_kwargs = {
            k: v for k, v in fla_layer_kwargs.items()
            if k in sig.parameters and k not in excluded
        }

        transformer_layers = self._get_transformer_layers(base_model)
        for i, layer in enumerate(transformer_layers):
            fla_layer = layer_cls(
                hidden_size=gdn_hidden_size,
                layer_idx=0,
                **filtered_kwargs,
            ).to(dtype=model_dtype, device=model_device)

            wrapped = RecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer,
                model_hidden_size=model_hidden_size,
                num_write_vectors=num_write_vectors,
                write_mode=write_mode,
                write_value_dim=write_value_dim,
                num_read_heads=num_read_heads,
            )
            transformer_layers[i] = wrapped

    def forward(self, input_ids: torch.Tensor, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)

    def generate(self, input_ids: torch.Tensor, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


class RecurrentMemoryWrapperBase(nn.Module):
    """Iterates over segments, accumulating GDN state across them.

    State persists implicitly in each RecurrentMemoryLayerWrapper (cache +
    last_write_output). Full BPTT within a sample by default.
    """

    def __init__(self, memory_cell: RecurrentMemoryCell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        cell_outputs = []
        for segment in segments:
            cell_out = self.memory_cell(
                input_ids=segment["input_ids"],
                attention_mask=segment["attention_mask"],
                output_hidden_states=True,
            )
            cell_outputs.append(cell_out)

        labels_mask = None
        if segments and "labels_mask" in segments[0]:
            labels_mask = torch.cat([seg["labels_mask"] for seg in segments], dim=1)

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

        if not cell_outputs:
            out["loss"] = torch.tensor(0.0)
            out["logits"] = torch.empty(0, 0, 0)
            return out

        full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)
        full_hidden_states = tuple(
            torch.cat(layer_hs, dim=1)
            for layer_hs in zip(*[o.hidden_states for o in cell_outputs])
        )

        labels = kwargs.get("labels")
        if labels is not None:
            shift_logits = full_logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            flat_logits  = shift_logits.view(-1, shift_logits.size(-1))
            flat_labels  = shift_labels.view(-1)

            labels_mask = kwargs.get("labels_mask")
            if labels_mask is not None:
                shift_mask  = labels_mask[..., :-1].contiguous().view(-1)
                flat_logits = flat_logits[shift_mask]
                flat_labels = flat_labels[shift_mask]

            out["loss"] = CrossEntropyLoss()(flat_logits, flat_labels)
        else:
            out["loss"] = torch.tensor(0.0)

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
            base_config = (
                config.base_model_config
                if config.base_model_config is not None
                else AutoConfig.from_pretrained(config.base_model_name)
            )
            base_model = AutoModelForCausalLM.from_config(base_config)

        self.rmm_config = config
        memory_cell = RecurrentMemoryCell(
            base_model,
            fla_layer_name=config.fla_layer_name,
            num_write_vectors=config.num_write_vectors,
            write_mode=config.write_mode,
            write_value_dim=config.write_value_dim,
            num_read_heads=config.num_read_heads,
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

    def _reset_memory(self):
        for layer in RecurrentMemoryCell._get_transformer_layers(self.rmt.memory_cell.model):
            layer.reset_memory()

    def forward(self, segments=None, labels=None, *args, **kwargs):
        out = self.rmt(segments=segments, labels=labels, *args, **kwargs)
        self._reset_memory()
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
                print(f"Warning: no weights found for {pretrained_model_name_or_path}. Randomly initialised.")

        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)

        return model
