import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

from transformers import StoppingCriteria
from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions


class RMCAConfig(PretrainedConfig):
    model_type = "rmt"

    def __init__(self,
                 base_model_name="HuggingFaceTB/SmolLM2-135M",
                 base_model_config=None,
                 from_pretrained=None,
                 num_mem_tokens=16,
                 max_n_segments=10,
                 think_token_id=None,
                 answer_token_id=None,
                 bos_token_id=None,
                 eos_token_id=None,
                 num_mem_heads=8,
                 num_read_blocks=1,
                 num_write_blocks=1,
                 memory_feedforward=False,
                 **kwargs):
        super().__init__(**kwargs)
        self.base_model_name = base_model_name
        self.base_model_config = base_model_config
        self.from_pretrained = from_pretrained
        self.num_mem_tokens = num_mem_tokens
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id
        self.num_read_blocks = num_read_blocks
        self.num_write_blocks = num_write_blocks
        self.memory_feedforward = memory_feedforward
        self.memory_cell_cls = "RMCACell"
        self.recurrent_wrapper_cls = "RMCAWrapperNoSegmentation"

    def get(self, attr: str, default=None):
        if hasattr(self, attr):
            return getattr(self, attr)
        else:
            return default


from transformers.models.llama.modeling_llama import apply_rotary_pos_emb


class LlamaCrossAttention(nn.Module):
    """Cross-attention with same structure as Llama (q/k/v/o, optional RoPE). Returns (attn_output, attn_weights).

    Differences from original Llama self-attention (LlamaAttention):
    - Cross-attention: Q from from_states, K/V from to_states (no past_key_values/cache).
    - Init from explicit args (hidden_size, num_heads, ...) instead of LlamaConfig and layer_idx.
    - Optional RoPE: position_embeddings is (cos_q, sin_q, cos_k, sin_k) for query/key positions; when None, no RoPE.
    - No causal mask or attention_implementation: plain scaled dot-product attention.
    - Always returns (output, attn_weights); attn_weights may be used for output_attentions.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        head_dim: int | None = None,
        num_key_value_heads: int | None = None,
        dropout: float = 0.0,
        bias: bool = False,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = head_dim if head_dim is not None else hidden_size // num_heads
        self.num_key_value_heads = num_key_value_heads if num_key_value_heads is not None else num_heads
        self.num_key_value_groups = num_heads // self.num_key_value_heads
        self.scaling = self.head_dim**-0.5
        self.attention_dropout = dropout

        self.q_proj = nn.Linear(hidden_size, num_heads * self.head_dim, bias=bias)
        self.k_proj = nn.Linear(hidden_size, self.num_key_value_heads * self.head_dim, bias=bias)
        self.v_proj = nn.Linear(hidden_size, self.num_key_value_heads * self.head_dim, bias=bias)
        self.o_proj = nn.Linear(num_heads * self.head_dim, hidden_size, bias=bias)

    def forward(
        self,
        from_states: torch.Tensor,
        to_states: torch.Tensor,
        position_embeddings: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor] | None = None,
        attention_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        batch_size, q_len, _ = from_states.shape
        k_len = to_states.shape[1]
        input_shape = from_states.shape[:-1]
        q_hidden_shape = (*input_shape, -1, self.head_dim)
        kv_hidden_shape = (batch_size, k_len, -1, self.head_dim)

        query_states = self.q_proj(from_states).view(q_hidden_shape).transpose(1, 2)
        key_states = self.k_proj(to_states).view(kv_hidden_shape).transpose(1, 2)
        value_states = self.v_proj(to_states).view(kv_hidden_shape).transpose(1, 2)

        if position_embeddings is not None:
            cos_q, sin_q, cos_k, sin_k = position_embeddings
            query_states, _ = apply_rotary_pos_emb(query_states, query_states, cos_q, sin_q)
            _, key_states = apply_rotary_pos_emb(key_states, key_states, cos_k, sin_k)

        if self.num_key_value_groups > 1:
            key_states = key_states.repeat_interleave(self.num_key_value_groups, dim=1)
            value_states = value_states.repeat_interleave(self.num_key_value_groups, dim=1)

        attn_weights = torch.matmul(query_states, key_states.transpose(-2, -1)) * self.scaling
        if attention_mask is not None:
            attn_weights = attn_weights + attention_mask
        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(query_states.dtype)
        attn_weights = F.dropout(
            attn_weights, p=self.attention_dropout if self.training else 0.0, training=self.training
        )

        attn_output = torch.matmul(attn_weights, value_states)
        attn_output = attn_output.transpose(1, 2).reshape(*input_shape, -1).contiguous()
        return self.o_proj(attn_output), attn_weights


class LlamaMLP(nn.Module):
    """Llama-style gated MLP (SwiGLU): gate_proj * silu(up_proj) -> down_proj."""

    def __init__(self, hidden_size: int, intermediate_size: int, bias: bool = False):
        super().__init__()
        self.gate_proj = nn.Linear(hidden_size, intermediate_size, bias=bias)
        self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=bias)
        self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=bias)
        self.act_fn = nn.SiLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(self.act_fn(self.gate_proj(x)) * self.up_proj(x))


class CrossAttentionBlock(nn.Module):
    """Single Llama-style cross-attention block: pre-norm cross-attn + pre-norm FFN, each with residual.

    Query source is `x`; key/value source is `context`.
    Both inputs and context are normalized inside the block, so raw (un-normed) tensors should be passed in.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        head_dim: int | None,
        num_key_value_heads: int | None,
        intermediate_size: int,
        dropout: float = 0.0,
        bias: bool = False,
    ):
        super().__init__()
        self.input_norm = nn.RMSNorm(hidden_size)
        self.context_norm = nn.RMSNorm(hidden_size)
        self.attn = LlamaCrossAttention(
            hidden_size=hidden_size,
            num_heads=num_heads,
            head_dim=head_dim,
            num_key_value_heads=num_key_value_heads,
            dropout=dropout,
            bias=bias,
        )
        self.ffn_norm = nn.RMSNorm(hidden_size)
        self.ffn = LlamaMLP(hidden_size=hidden_size, intermediate_size=intermediate_size, bias=bias)

    def forward(self, x: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.input_norm(x), self.context_norm(context))[0]
        x = x + self.ffn(self.ffn_norm(x))
        return x


class CrossAttentionStack(nn.Module):
    """Stack of `num_blocks` CrossAttentionBlocks applied sequentially."""

    def __init__(
        self,
        num_blocks: int,
        hidden_size: int,
        num_heads: int,
        head_dim: int | None,
        num_key_value_heads: int | None,
        intermediate_size: int,
        dropout: float = 0.0,
        bias: bool = False,
    ):
        super().__init__()
        block_kwargs = dict(
            hidden_size=hidden_size,
            num_heads=num_heads,
            head_dim=head_dim,
            num_key_value_heads=num_key_value_heads,
            intermediate_size=intermediate_size,
            dropout=dropout,
            bias=bias,
        )
        self.blocks = nn.ModuleList([CrossAttentionBlock(**block_kwargs) for _ in range(num_blocks)])

    def forward(self, x: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        for block in self.blocks:
            x = block(x, context)
        return x


class MemoryAugmentedLayer(nn.Module):
    """Wraps a transformer layer with memory read/write via cross-attention stacks."""

    def __init__(self, base_layer, memory_read_stack, memory_write_stack, initial_memory_state):
        super().__init__()
        self.base_layer = base_layer
        self.memory_read = memory_read_stack
        self.memory_write = memory_write_stack
        self.register_buffer('initial_memory_state', initial_memory_state)
        self.memory_state = initial_memory_state

    def forward(self, hidden_states, *args, **kwargs):
        batch_size = hidden_states.shape[0]
        if self.memory_state.shape[0] != batch_size:
            memory = self.initial_memory_state.expand(batch_size, -1, -1).to(hidden_states.device)
        else:
            memory = self.memory_state.to(hidden_states.device)

        # Read: update hidden states using memory as context
        hidden_states = self.memory_read(hidden_states, memory)

        # Write: update memory using (updated) hidden states as context
        memory = self.memory_write(memory, hidden_states)
        self.memory_state = memory

        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    def reset_memory(self):
        self.memory_state = self.initial_memory_state


class RMCACell(torch.nn.Module):
    def __init__(self, base_model, num_mem_tokens, num_heads=8,
                 num_read_blocks=1, num_write_blocks=1):
        super().__init__()
        self.model = base_model
        self.num_mem_tokens = num_mem_tokens

        hidden_size = getattr(base_model.config, "n_embd", base_model.config.hidden_size)
        num_attention_heads = getattr(base_model.config, "num_attention_heads", num_heads)
        num_key_value_heads = getattr(base_model.config, "num_key_value_heads", num_attention_heads)
        head_dim = getattr(base_model.config, "head_dim", hidden_size // num_attention_heads)
        attention_dropout = getattr(base_model.config, "attention_dropout", 0.0)
        attention_bias = getattr(base_model.config, "attention_bias", False)
        intermediate_size = getattr(base_model.config, "intermediate_size", hidden_size * 4)

        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        stack_kwargs = dict(
            hidden_size=hidden_size,
            num_heads=num_attention_heads,
            head_dim=head_dim,
            num_key_value_heads=num_key_value_heads,
            intermediate_size=intermediate_size,
            dropout=attention_dropout,
            bias=attention_bias,
        )

        for i, layer in enumerate(self.model.model.layers):
            memory_read = CrossAttentionStack(num_blocks=num_read_blocks, **stack_kwargs)
            memory_write = CrossAttentionStack(num_blocks=num_write_blocks, **stack_kwargs)
            initial_memory = torch.randn(1, num_mem_tokens, hidden_size) / math.sqrt(hidden_size)
            wrapped_layer = MemoryAugmentedLayer(
                layer.to(dtype=model_dtype, device=model_device),
                memory_read.to(dtype=model_dtype, device=model_device),
                memory_write.to(dtype=model_dtype, device=model_device),
                initial_memory.to(dtype=model_dtype, device=model_device),
            )
            self.model.model.layers[i] = wrapped_layer

    def forward(self, input_ids, **kwargs):
        out = self.model(input_ids=input_ids, **kwargs)
        # memory_state = [layer.memory_state for layer in self.model.model.layers]
        return out

    def generate(self, input_ids, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


class RMCAWrapperBase(torch.nn.Module):
    def __init__(self, memory_cell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        cell_outputs = []
        for seg_num, segment in enumerate(segments):
            cell_out = self.memory_cell(input_ids=segment['input_ids'],
                                        attention_mask=segment['attention_mask'],
                                        output_hidden_states=True)
            cell_outputs.append(cell_out)

        # Extract labels_mask from segments if available
        labels_mask = None
        if 'labels_mask' in segments[0]:
            labels_mask = torch.cat([seg['labels_mask'] for seg in segments], dim=1)

        out = self.process_outputs(cell_outputs,
                                   labels=labels,
                                   labels_mask=labels_mask,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states,
                                   **kwargs
                                   )
        return out

    def generate(self, segments, **kwargs):
        raise NotImplementedError("Generation is not implemented for RMCAWrapperBase")
        memory_state = None

        for seg_num, segment in enumerate(segments):
            cell_out, memory_state = self.memory_cell(input_ids=segment['input_ids'],
                                                      attention_mask=segment['attention_mask'],
                                                      memory_state=memory_state, output_hidden_states=True)

        generated_segments = []
        for seg_num in range(len(segments), self.rmt_config.get("max_n_segments", 32)):
            output_ids, memory_state = self.generate_segment(memory_state=memory_state, **kwargs)
            generated_segments.append(output_ids)

            if self.all_done(generated_segments):
                break

        return generated_segments

    def generate_segment(self, memory_state, **kwargs):
        raise NotImplementedError("Generation is not implemented for RMCAWrapperBase")
        # input_ids = self.get_bos_tensor(memory_state)
        # attention_mask = torch.ones_like(input_ids).bool()

        # generated = self.memory_cell.generate(
        #     input_ids=input_ids,
        #     attention_mask=attention_mask,
        #     memory_state=memory_state,
        #     eos_token_id=[self.rmt_config['think_token_id'], self.rmt_config['answer_token_id']],
        #     **kwargs
        # )

        # # Update memory state from generation
        # fwd_inputs = torch.cat((input_ids, generated), dim=1)[:, :-1]
        # _, memory_state = self.memory_cell(input_ids=fwd_inputs, memory_state=memory_state)

        # return generated, memory_state

    # def get_bos_tensor(self, memory_state):
    #     bos = self.rmt_config["bos_token_id"]
    #     bos_tensor = torch.tensor([bos] * memory_state.shape[0]).reshape(-1, 1)
    #     return bos_tensor.to(memory_state.device)

    # def all_done(self, generated_segments):
    #     eos = self.rmt_config['eos_token_id']
    #     bs = generated_segments[0].shape[0]
    #     have_eos = [any([eos in seg[i] for seg in generated_segments]) for i in range(bs)]
    #     all_done = all(have_eos)
    #     return all_done

    def process_outputs(self, cell_outputs, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)
        full_hidden_states = tuple([torch.cat(layer_hs, dim=1)
                                    for layer_hs in zip(*[o.hidden_states for o in cell_outputs])])

        labels = kwargs.get('labels')
        if labels is not None:
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            loss_fct = CrossEntropyLoss()
            labels_mask = kwargs.get('labels_mask')
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous()

                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]

            out['loss'] = loss_fct(flat_logits, flat_labels)
        else:
            out['loss'] = 0

        out['logits'] = full_logits
        segment_keys = ['loss', 'logits']
        if kwargs.get('output_attentions'):
            segment_keys.append('attentions')
        if kwargs.get('output_hidden_states'):
            segment_keys.append('hidden_states')
            out['hidden_states'] = full_hidden_states

        return out

    def manage_gradients(self, memory_state, seg_num):
        k2, max_n_segments = self.rmt_config.get('k2'), self.rmt_config.get('max_n_segments')
        if seg_num == 0 \
            or k2 in {-1, None} \
                or seg_num + k2 > max_n_segments:
            return memory_state

        memory_state = memory_state.detach()
        return memory_state

    def gradient_checkpointing_enable(self, *args, **kwargs):
        self.memory_cell.model.gradient_checkpointing_enable(*args, **kwargs)


class RMCABase(PreTrainedModel):
    config_class = RMCAConfig

    def __init__(self, config: RMCAConfig, **kwargs):
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

        self.rmt_config = config
        memory_cell = RMCACell(
            base_model,
            num_mem_tokens=config.num_mem_tokens,
            num_heads=config.num_mem_heads,
            num_read_blocks=config.num_read_blocks,
            num_write_blocks=config.num_write_blocks,
        )
        self.rmt = RMCAWrapperBase(
            memory_cell,
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id
        )

    def forward(self, labels=None, *args, **kwargs):
        out = self.rmt(labels=labels, *args, **kwargs)
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
        import torch

        if config is None:
            config = RMCAConfig.from_pretrained(pretrained_model_name_or_path, **kwargs)

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
                print(f"Warning: Could not find weights for {pretrained_model_name_or_path}. "
                      f"The model is initialized randomly.")

        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)

        return model