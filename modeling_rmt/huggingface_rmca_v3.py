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
                 use_deep_supervision=False,
                 deep_supervision_weight=0.1,
                 deep_supervision_layers=None,
                 use_segment_curriculum=False,
                 curriculum_start_ratio=0.5,
                 curriculum_steps=10000,
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
        self.memory_cell_cls = "RMCACell"
        self.recurrent_wrapper_cls = "RMCAWrapperNoSegmentation"
        self.use_deep_supervision = use_deep_supervision
        self.deep_supervision_weight = deep_supervision_weight
        self.deep_supervision_layers = deep_supervision_layers
        self.use_segment_curriculum = use_segment_curriculum
        self.curriculum_start_ratio = curriculum_start_ratio
        self.curriculum_steps = curriculum_steps

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


class MemoryAugmentedLayer(nn.Module):
    """Wraps a transformer layer with memory read/write via cross-attention"""
    def __init__(self, base_layer, memory_read_layer, memory_write_layer, initial_memory_state, config=None):
        super().__init__()
        self.base_layer = base_layer
        self.memory_read = memory_read_layer
        self.memory_write = memory_write_layer
        self.register_buffer('initial_memory_state', initial_memory_state)
        self.memory_state = initial_memory_state

        self.memory_layer_norm = torch.nn.RMSNorm(initial_memory_state.shape[-1])
        self.input_layer_norm = torch.nn.RMSNorm(initial_memory_state.shape[-1])
        self.pre_base_layer_norm = torch.nn.RMSNorm(initial_memory_state.shape[-1])
        self.post_base_layer_norm = torch.nn.RMSNorm(initial_memory_state.shape[-1])
        self.memory_dropout = torch.nn.Dropout(config.get('memory_dropout', 0.0) if config else 0.0)
        self.write_gate = nn.Parameter(torch.tensor(0.5))
    
    def forward(self, hidden_states, *args, **kwargs):
        batch_size = hidden_states.shape[0]
        if self.memory_state.shape[0] != batch_size:
            memory = self.initial_memory_state.expand(batch_size, -1, -1).to(hidden_states.device)
        else:
            memory = self.memory_state.to(hidden_states.device)
        
        # Read from memory
        memory_normed = self.memory_layer_norm(memory)
        hidden_states_normed = self.input_layer_norm(hidden_states)
        
        read_out = self.memory_read(hidden_states_normed, memory_normed)
        read_residual = read_out[0] if isinstance(read_out, tuple) else read_out
        read_attn_weights = read_out[1] if isinstance(read_out, tuple) and len(read_out) > 1 else None
        read_residual = self.memory_dropout(read_residual)
        hidden_states = hidden_states + read_residual

        # Write to memory
        write_out = self.memory_write(memory_normed, hidden_states_normed)
        write_residual = write_out[0] if isinstance(write_out, tuple) else write_out
        write_attn_weights = write_out[1] if isinstance(write_out, tuple) and len(write_out) > 1 else None
        write_residual = self.memory_dropout(write_residual)
        memory = memory + self.write_gate * write_residual
        self.memory_state = memory

        # Base layer forward
        # hidden_states = self.pre_base_layer_norm(hidden_states)
        output = self.base_layer(hidden_states, *args, **kwargs)
        # hidden_states = hidden_states + (output[0] if isinstance(output, tuple) else output)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # Pass through base layer outputs (hidden_states, cache?, attentions?) and append cross-attention weights
        if isinstance(output, tuple):
            cross_attentions = (read_attn_weights, write_attn_weights)
            return (hidden_states,) + output[1:] + (cross_attentions,)
        return hidden_states
    
    def reset_memory(self):
        self.memory_state = self.initial_memory_state


class RMCACell(torch.nn.Module):
    def __init__(self, base_model, num_mem_tokens, num_heads=8):
        super().__init__()
        self.model = base_model
        self.num_mem_tokens = num_mem_tokens

        hidden_size = getattr(base_model.config, "n_embd", base_model.config.hidden_size)
        num_attention_heads = getattr(base_model.config, "num_attention_heads", num_heads)
        num_key_value_heads = getattr(base_model.config, "num_key_value_heads", num_attention_heads)
        head_dim = getattr(base_model.config, "head_dim", hidden_size // num_attention_heads)
        attention_dropout = getattr(base_model.config, "attention_dropout", 0.0)
        attention_bias = getattr(base_model.config, "attention_bias", False)

        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device
        for i, layer in enumerate(self.model.model.layers):
            memory_read = LlamaCrossAttention(
                hidden_size=hidden_size,
                num_heads=num_attention_heads,
                head_dim=head_dim,
                num_key_value_heads=num_key_value_heads,
                dropout=attention_dropout,
                bias=attention_bias,
            ).to(dtype=model_dtype, device=model_device)
            memory_write = LlamaCrossAttention(
                hidden_size=hidden_size,
                num_heads=num_attention_heads,
                head_dim=head_dim,
                num_key_value_heads=num_key_value_heads,
                dropout=attention_dropout,
                bias=attention_bias,
            ).to(dtype=model_dtype, device=model_device)
            # initial_memory = self.memory.unsqueeze(0).to(dtype=model_dtype, device=model_device)
            initial_memory = torch.randn(1, num_mem_tokens, hidden_size) / math.sqrt(hidden_size)
            wrapped_layer = MemoryAugmentedLayer(
                layer.to(dtype=model_dtype, device=model_device),
                memory_read.to(dtype=model_dtype, device=model_device),
                memory_write.to(dtype=model_dtype, device=model_device),
                initial_memory.to(dtype=model_dtype, device=model_device)
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
        self._global_step = 0

    def get_curriculum_mask(self, seq_len):
        """Compute effective length mask for segment-length curriculum.
        
        During early training, gradually expand the effective attention scope from
        curriculum_start_ratio to 1.0 over curriculum_steps.
        
        Args:
            seq_len: Total sequence length
            
        Returns:
            Tensor of shape (1, seq_len) with 1s for valid positions and 0s for masked positions
        """
        use_curriculum = self.rmt_config.get('use_segment_curriculum', False)
        if not use_curriculum:
            return None
        
        curriculum_start_ratio = self.rmt_config.get('curriculum_start_ratio', 0.5)
        curriculum_steps = self.rmt_config.get('curriculum_steps', 10000)
        
        # Compute current progress (0 to 1)
        progress = min(self._global_step / curriculum_steps, 1.0)
        
        # Current effective ratio: starts at curriculum_start_ratio, grows to 1.0
        current_ratio = curriculum_start_ratio + progress * (1.0 - curriculum_start_ratio)
        
        # Compute number of tokens to keep
        effective_len = int(current_ratio * seq_len)
        
        # Create mask: 1s for first effective_len tokens, 0s for rest
        mask = torch.zeros(1, seq_len, device=self.rmt_config.get('device', 'cpu'))
        mask[0, :effective_len] = 1.0
        
        return mask
    
    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None, *args, **kwargs):
        # Update global step for curriculum computation
        self._global_step += 1
        
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

        # Compute curriculum mask if enabled
        curriculum_mask = None
        if self.rmt_config.get('use_segment_curriculum', False):
            total_seq_len = sum(seg['input_ids'].shape[1] for seg in segments)
            curriculum_mask = self.get_curriculum_mask(total_seq_len)

        out = self.process_outputs(cell_outputs,
                                   labels=labels,
                                   labels_mask=labels_mask,
                                   output_attentions=output_attentions,
                                   output_hidden_states=output_hidden_states,
                                   curriculum_mask=curriculum_mask,
                                   **kwargs
                                   )
        return out

    def generate(self, segments, **kwargs):
        raise NotImplementedError("Generation is not implemented for RMCAWrapperBase")

    def generate_segment(self, memory_state, **kwargs):
        raise NotImplementedError("Generation is not implemented for RMCAWrapperBase")

    def process_outputs(self, cell_outputs, **kwargs):
        out = CausalLMOutputWithCrossAttentions()
        full_logits = torch.cat([o.logits for o in cell_outputs], dim=1)
        full_hidden_states = tuple([torch.cat(layer_hs, dim=1)
                                    for layer_hs in zip(*[o.hidden_states for o in cell_outputs])])

        labels = kwargs.get('labels')
        loss_fct = CrossEntropyLoss()
        
        # Main loss computation
        if labels is not None:
            shift_labels = labels[..., 1:].contiguous()
            shift_logits = full_logits[..., :-1, :].contiguous()
            flat_labels = shift_labels.view(-1)
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))

            labels_mask = kwargs.get('labels_mask')
            curriculum_mask = kwargs.get('curriculum_mask')
            
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous()
                flat_labels = flat_labels[shift_mask.view(-1)]
                flat_logits = flat_logits[shift_mask.view(-1)]
            
            # Apply curriculum mask to limit attention scope
            if curriculum_mask is not None:
                curriculum_mask_expanded = curriculum_mask[..., :-1].contiguous()
                if labels_mask is None:
                    flat_labels = flat_labels[curriculum_mask_expanded.view(-1)]
                    flat_logits = flat_logits[curriculum_mask_expanded.view(-1)]
                else:
                    combined_mask = shift_mask * curriculum_mask_expanded
                    flat_labels = flat_labels[combined_mask.view(-1)]
                    flat_logits = flat_logits[combined_mask.view(-1)]

            main_loss = loss_fct(flat_logits, flat_labels)
        else:
            main_loss = torch.tensor(0.0, device=full_logits.device)

        # Deep supervision loss computation
        use_deep_supervision = self.rmt_config.get('use_deep_supervision', False)
        deep_supervision_layers = self.rmt_config.get('deep_supervision_layers', None)
        deep_supervision_weight = self.rmt_config.get('deep_supervision_weight', 0.1)
        
        if use_deep_supervision and deep_supervision_layers is not None and labels is not None:
            deep_supervision_loss = 0.0
            n_layers = len(full_hidden_states)
            
            for layer_idx in deep_supervision_layers:
                if 0 <= layer_idx < n_layers:
                    layer_hidden_states = full_hidden_states[layer_idx]
                    # Apply layer norm to hidden states before computing logits
                    # The hidden states need to be projected to vocab space
                    # Use the final layer's lm_head for consistency
                    # For simplicity, compute loss on intermediate hidden states
                    # by projecting through a linear layer (would need lm_head reference)
                    # Instead, we compute auxiliary loss on hidden states directly
                    
                    # Get intermediate logits from cell outputs at this layer
                    # Each cell_output contains hidden_states for all layers up to that segment
                    # We need to extract the hidden state at the specified layer index
                    
                    layer_logits = full_hidden_states[layer_idx]
                    shift_layer_labels = labels[..., 1:].contiguous()
                    shift_layer_logits = layer_logits[..., :-1, :].contiguous()
                    flat_layer_labels = shift_layer_labels.view(-1)
                    flat_layer_logits = shift_layer_logits.view(-1, shift_layer_logits.size(-1))
                    
                    if labels_mask is not None:
                        shift_mask = labels_mask[..., :-1].contiguous()
                        flat_layer_labels = flat_layer_labels[shift_mask.view(-1)]
                        flat_layer_logits = flat_layer_logits[shift_mask.view(-1)]
                    
                    layer_loss = loss_fct(flat_layer_logits, flat_layer_labels)
                    deep_supervision_loss = deep_supervision_loss + layer_loss
            
            # Average the deep supervision losses
            n_supervised_layers = len([l for l in deep_supervision_layers if 0 <= l < n_layers])
            if n_supervised_layers > 0:
                deep_supervision_loss = deep_supervision_loss / n_supervised_layers
            
            total_loss = main_loss + deep_supervision_weight * deep_supervision_loss
        else:
            total_loss = main_loss

        out['loss'] = total_loss
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
        memory_cell = RMCACell(base_model, num_mem_tokens=config.num_mem_tokens, num_heads=config.num_mem_heads)
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