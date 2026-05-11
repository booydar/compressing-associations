import inspect
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss
import math

from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions

import fla.layers
from fla.models.utils import Cache


class RecurrentLayerWithSkip(nn.Module):
    """Recurrent layer (GDN, Mamba2, etc.) with skip connection from input to output."""

    def __init__(self, original_layer: nn.Module):
        super().__init__()
        self.layer = original_layer

    def forward(self, hidden_states, *args, **kwargs):
        output = self.layer(hidden_states, *args, **kwargs)
        out_tensor = output[0] if isinstance(output, tuple) else output
        if isinstance(output, tuple):
            return (hidden_states + out_tensor,) + output[1:]
        return hidden_states + out_tensor


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


class MemoryWriter(nn.Module):
    """Compresses T segment tokens → M memory vectors of dim d_v.

    mode='pool':
        M learnable query vectors (no Q proj) attend to K/V from tokens.
    mode='cross_attn':
        Same + Q proj on queries + out proj on result.
    """

    def __init__(
        self,
        hidden_size: int,
        num_vectors: int,
        mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        bias: bool = False,
    ):
        super().__init__()
        if mode not in ('pool', 'cross_attn'):
            raise ValueError(f"MemoryWriter mode must be 'pool' or 'cross_attn', got '{mode}'")

        self.mode = mode
        self.write_value_dim = write_value_dim or hidden_size
        self.scaling = hidden_size ** -0.5

        self.write_queries = nn.Parameter(torch.zeros(num_vectors, hidden_size))
        # v5: scale-correct init so logits ~ N(0,1) after Q·K^T/√d at init,
        # avoiding the near-uniform softmax that std=0.02 produces.
        nn.init.normal_(self.write_queries, std=hidden_size ** -0.5)

        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
        self.v_proj = nn.Linear(hidden_size, self.write_value_dim, bias=bias)

        if mode == 'cross_attn':
            self.q_proj  = nn.Linear(hidden_size, hidden_size, bias=bias)
            self.out_proj = nn.Linear(self.write_value_dim, self.write_value_dim, bias=bias)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """(B, T, d) -> (B, M, d_v)"""
        B = hidden_states.shape[0]
        queries = self.write_queries.unsqueeze(0).expand(B, -1, -1)   # (B, M, d)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)

        k = self.k_proj(hidden_states)   # (B, T, d)
        v = self.v_proj(hidden_states)   # (B, T, d_v)

        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling   # (B, M, T)
        attn = F.softmax(attn, dim=-1)
        write_vecs = torch.matmul(attn, v)   # (B, M, d_v)

        if self.mode == 'cross_attn':
            write_vecs = self.out_proj(write_vecs)

        return write_vecs


class MemoryReader(nn.Module):
    """Enriches T tokens from M memory vectors of dim d_v.

    mode='unpool':
        Tokens attend to memory; K/V projected from d_v→d; no Q proj on tokens.
        Symmetric dual of MemoryWriter 'pool'.
    mode='cross_attn':
        Full LlamaCrossAttention(hidden_size=d, kv_hidden_size=d_v).
    """

    def __init__(
        self,
        hidden_size: int,
        write_value_dim: int,
        mode: str = 'cross_attn',
        num_heads: int = 1,
        bias: bool = False,
    ):
        super().__init__()
        if mode not in ('unpool', 'cross_attn'):
            raise ValueError(f"MemoryReader mode must be 'unpool' or 'cross_attn', got '{mode}'")

        self.mode = mode
        self.scaling = hidden_size ** -0.5

        if mode == 'unpool':
            self.k_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
            self.v_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
        else:
            self.cross_attn = LlamaCrossAttention(
                hidden_size=hidden_size,
                num_heads=num_heads,
                kv_hidden_size=write_value_dim,
                out_hidden_size=hidden_size,
            )

    def forward(self, token_states: torch.Tensor, memory_states: torch.Tensor) -> torch.Tensor:
        """(B, T, d), (B, M, d_v) -> (B, T, d)"""
        if self.mode == 'unpool':
            k = self.k_proj(memory_states)   # (B, M, d)
            v = self.v_proj(memory_states)   # (B, M, d)
            attn = torch.matmul(token_states, k.transpose(-1, -2)) * self.scaling   # (B, T, M)
            attn = F.softmax(attn, dim=-1)
            return torch.matmul(attn, v)   # (B, T, d)
        else:
            out, _ = self.cross_attn(from_states=token_states, to_states=memory_states)
            return out


class RecurrentMemoryLayerWrapper(nn.Module):
    """Wraps a transformer layer with symmetric read/write memory via GDN.

    Each segment:
      1. READ  – enrich tokens from last segment's memory (B,M,d_v). Skipped on
                 first segment or when read_mode='identity'.
      2. ATTN  – base transformer layer.
      3. WRITE – compress tokens → GDN → store memory at full d_v.
                 In identity mode the GDN processes all T tokens directly and
                 its output is residual-added immediately (no stored memory).
      4. (v5) WRITE-RESIDUAL – if write_residual=True and read_mode != identity,
                 enrich post-write tokens from this segment's fresh memory.

    Symmetric mode pairs: identity/identity, pool/unpool, cross_attn/cross_attn.
    Asymmetric pairs (pool/cross_attn, cross_attn/unpool) also work.
    v5 read_mode 'gdn_readout': skip MemoryReader entirely; pass tokens through
    fla_layer with cached state but DO NOT update the cache. Requires
    write_value_dim == model_hidden_size.
    Constraint: identity write must be paired with identity read.
    
    Dual-state mechanism: maintains fast_state (short-term) and slow_state 
    (long-term) with separate decay rates. Gate combines outputs from both.
    """

    def __init__(
        self,
        base_layer: nn.Module,
        fla_layer: nn.Module,
        model_hidden_size: int,
        num_memory_vectors: int = 1,
        write_mode: str = 'cross_attn',
        read_mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        num_memory_heads: int = 1,
        write_residual: bool = False,
    ):
        super().__init__()
        if write_mode == 'identity' and read_mode != 'identity':
            raise ValueError("identity write_mode must be paired with identity read_mode")

        write_value_dim_resolved = write_value_dim or model_hidden_size
        if read_mode == 'identity' and write_value_dim_resolved != model_hidden_size:
            raise ValueError(
                "read_mode='identity' requires write_value_dim == model_hidden_size "
                f"(got write_value_dim={write_value_dim_resolved}, hidden={model_hidden_size})"
            )
        # if read_mode == 'identity' and write_mode == 'identity':
        #     raise ValueError("read_mode='identity' is incompatible with write_mode='identity'")

        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.write_residual = write_residual

        self.write_value_dim = write_value_dim_resolved

        self.write_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)
        self.read_norm  = nn.RMSNorm(model_hidden_size, eps=1e-5)

        if write_mode == 'identity':
            self.fla_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)
        else:
            self.memory_writer = MemoryWriter(
                hidden_size=model_hidden_size,
                num_vectors=num_memory_vectors,
                mode=write_mode,
                write_value_dim=self.write_value_dim,
            )
            if read_mode in ('unpool', 'cross_attn'):
                self.memory_reader = MemoryReader(
                    hidden_size=model_hidden_size,
                    write_value_dim=self.write_value_dim,
                    mode=read_mode,
                    num_heads=num_memory_heads,
                )

        self.cache = Cache()
        self.last_write_output: torch.Tensor | None = None   # (B, M, d_v)

    def _gdn_readonly(self, normed_tokens, attention_mask):
        """Run fla_layer with cached state but discard any state update."""
        if len(self.cache.layers) == 0:
            # No prior state — readout is undefined. Return zeros.
            return torch.zeros_like(normed_tokens)
        layer = self.cache.layers[0]
        saved_state = layer.state if layer.state is None else dict(layer.state)
        saved_seen = layer._seen_tokens
        fla_out = self.fla_layer(
            normed_tokens,
            attention_mask=attention_mask,
            past_key_values=self.cache,
            use_cache=True,
        )
        # Restore state to discard the write that happened during readout
        layer.state = saved_state
        layer._seen_tokens = saved_seen
        return fla_out[0]
    
    def forward(self, hidden_states: torch.Tensor, *args, **kwargs):
        attention_mask = kwargs.get('attention_mask')

        # 1. READ
        if self.read_mode == 'identity':
            hidden_states = hidden_states + self._gdn_readonly(
                self.read_norm(hidden_states), attention_mask
            )
        elif self.read_mode in ('unpool', 'cross_attn') and self.last_write_output is not None:
            hidden_states = hidden_states + self.memory_reader(
                self.read_norm(hidden_states), self.last_write_output
            )

        # 2. Base transformer layer
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # 3. WRITE
        if self.write_mode == 'identity':
            fla_input = self.fla_norm(hidden_states)
            
            fla_out = self.fla_layer(
                fla_input,
                attention_mask=attention_mask,
                past_key_values=self.cache,
                use_cache=True,
            )
            hidden_states = hidden_states + fla_out[0]
            self.cache = fla_out[2]
        else:
            write_vecs = self.memory_writer(self.write_norm(hidden_states))   # (B, M, d_v)
            
            fla_out = self.fla_layer(
                write_vecs,
                attention_mask=None,
                past_key_values=self.cache,
                use_cache=True,
            )
            self.last_write_output = fla_out[0]   # (B, M, d_v) — stored at full d_v
            self.cache = fla_out[2]

            # 4. (v5) write_residual: feed fresh memory back into current tokens.
            if self.write_residual and self.read_mode in ('unpool', 'cross_attn'):
                hidden_states = hidden_states + self.memory_reader(
                    self.read_norm(hidden_states), self.last_write_output
                )

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
        fla_layer_name="Mamba2",
        num_heads=1,
        head_dim=64,
        expand_v=2.0,
        conv_size=4,
        state_size=32,
        # Write/read modes
        write_mode='cross_attn',       # 'identity' | 'pool' | 'cross_attn'
        read_mode='cross_attn',        # 'identity' | 'unpool' | 'cross_attn'
        write_residual=False,          # v5: intra-segment residual after WRITE
        # Memory dimensions
        num_memory_vectors=1,          # M — number of memory vectors
        write_value_dim=None,          # d_v — memory dim; None = same as model hidden_size
        num_memory_heads=1,            # heads for read cross_attn
        # Old names kept as aliases (resolved in __init__)
        num_write_vectors=None,
        num_read_heads=None,
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
        self.state_size = state_size
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.write_residual = write_residual
        # Resolve aliases
        self.num_memory_vectors = num_write_vectors if num_write_vectors is not None else num_memory_vectors
        self.write_value_dim = write_value_dim
        self.num_memory_heads = num_read_heads if num_read_heads is not None else num_memory_heads
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    # Backward-compat aliases
    @property
    def num_write_vectors(self):
        return self.num_memory_vectors

    @property
    def num_read_heads(self):
        return self.num_memory_heads

    def get(self, attr: str, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self) -> dict:
        # SLA (Sliding Linear Attention) parameters
        return {
            "num_heads": 4,
            "head_dim": 8,
            "state_size": 32,
        }


class RecurrentMemoryCell(nn.Module):
    """Replaces each transformer layer with a RecurrentMemoryLayerWrapper.

    GDN hidden_size = d for identity mode, else write_value_dim (defaults to d).
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
        fla_layer_name: str = "Mamba2",
        num_memory_vectors: int = 1,
        write_mode: str = 'cross_attn',
        read_mode: str = 'cross_attn',
        write_value_dim: int | None = None,
        num_memory_heads: int = 1,
        write_residual: bool = False,
        **fla_layer_kwargs,
    ):
        super().__init__()
        self.model = base_model

        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        gdn_hidden_size = model_hidden_size if write_mode == 'identity' else (write_value_dim or model_hidden_size)
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
            fla_layer = RecurrentLayerWithSkip(fla_layer)

            wrapped = RecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer,
                model_hidden_size=model_hidden_size,
                num_memory_vectors=num_memory_vectors,
                write_mode=write_mode,
                read_mode=read_mode,
                write_value_dim=write_value_dim,
                num_memory_heads=num_memory_heads,
                write_residual=write_residual,
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
            num_memory_vectors=config.num_memory_vectors,
            write_mode=config.write_mode,
            read_mode=config.read_mode,
            write_value_dim=config.write_value_dim,
            num_memory_heads=config.num_memory_heads,
            write_residual=config.write_residual,
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
