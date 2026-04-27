# === ARMT with Gated Delta Net (GDN) Update Rule ===
# Maintains memory tokens but uses full GDN update mechanism

import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np
from torch.nn import TransformerEncoder, TransformerEncoderLayer
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions
from transformers.cache_utils import Cache, DynamicCache
import os


# === ACT Utils (from original ARMT) ===

def gen_timing_signal(length, channels, min_timescale=1.0, max_timescale=1.0e4):
    """Generate sinusoidal timing signals"""
    position = np.arange(length)
    num_timescales = channels // 2
    log_timescale_increment = (math.log(float(max_timescale) / float(min_timescale)) / 
                               (float(num_timescales) - 1))
    inv_timescales = min_timescale * np.exp(np.arange(num_timescales).astype(float) * 
                                            -log_timescale_increment)
    scaled_time = np.expand_dims(position, 1) * np.expand_dims(inv_timescales, 0)
    signal = np.concatenate([np.sin(scaled_time), np.cos(scaled_time)], axis=1)
    signal = np.pad(signal, [[0, 0], [0, channels % 2]], 
                    'constant', constant_values=[0.0, 0.0])
    signal = signal.reshape([1, length, channels])
    return torch.from_numpy(signal).type(torch.FloatTensor)


def relu(x):
    return torch.nn.functional.relu(x)


def dpfp(x, nu=1):
    """Directed Piecewise Feature Mapping"""
    x = torch.cat([relu(x), relu(-x)], dim=-1)
    x_rolled = torch.cat([x.roll(shifts=j, dims=-1) for j in range(1, nu+1)], dim=-1)
    x_repeat = torch.cat([x] * nu, dim=-1)
    return x_repeat * x_rolled


class DPFP:
    def __init__(self, nu):
        self.nu = nu
    
    def __call__(self, x):
        nu = self.nu
        x = torch.cat([relu(x), relu(-x)], dim=-1)
        x_rolled = torch.cat([x.roll(shifts=j, dims=-1) for j in range(1, nu+1)], dim=-1)
        x_repeat = torch.cat([x] * nu, dim=-1)
        return x_repeat * x_rolled


class ACT_basic(nn.Module):
    """Adaptive Computation Time for recurrent refinement"""
    def __init__(self, hidden_size):
        super(ACT_basic, self).__init__()
        self.sigma = nn.Sigmoid()
        self.p = nn.Linear(hidden_size, 1)
        self.p.bias.data.fill_(1)
        self.threshold = 1 - 0.1
        self.eps = 0.1

    def forward(self, *args, state, inputs, fn, time_enc, pos_enc, max_hop, 
                encoder_output=None, **kwargs):
        noisy_halting = kwargs.get('noisy_halting', False)
        
        halting_probability = torch.zeros(inputs.shape[0], inputs.shape[1]).to(inputs.device)
        remainders = torch.zeros(inputs.shape[0], inputs.shape[1]).to(inputs.device)
        n_updates = torch.zeros(inputs.shape[0], inputs.shape[1]).to(inputs.device)
        previous_state = torch.zeros_like(inputs).to(inputs.device)
        step = 0
        rest = None

        while ((halting_probability < self.threshold) & (n_updates < max_hop)).byte().any():
            p = self.sigma(self.p(state)).squeeze(-1)
            if noisy_halting and self.training:
                p = p + torch.randn_like(p) * self.eps
            
            still_running = (halting_probability < 1.0).float()
            new_halted = (halting_probability + p * still_running > self.threshold).float() * still_running
            still_running = (halting_probability + p * still_running <= self.threshold).float() * still_running
            
            halting_probability = halting_probability + p * still_running
            remainders = remainders + new_halted * (1 - halting_probability)
            halting_probability = halting_probability + new_halted * remainders
            n_updates = n_updates + still_running + new_halted
            update_weights = p * still_running + new_halted * remainders

            if encoder_output:
                state, _ = fn((state, encoder_output))
            else:
                state = fn(state, *args, **kwargs)
                if isinstance(state, tuple):
                    rest = state[1:]
                    state = state[0]

            previous_state = ((state * update_weights.unsqueeze(-1)) + 
                             (previous_state * (1 - update_weights.unsqueeze(-1))))
            step += 1
            
        if rest is None:
            return previous_state, (remainders, n_updates)
        else:
            return (previous_state, *rest), (remainders, n_updates)


# === GDN Update Rule Implementation ===

class GDNUpdateRule(nn.Module):
    """
    Full Gated Delta Net update rule applied to ARMT memory.
    
    At each segment boundary:
    1. Apply forget gate decay to existing memory
    2. Compute residual values (v - h @ k^T)
    3. Apply update gate
    4. Perform rank-1 update: h += k * v_residual
    """
    def __init__(self, d_model, d_mem, n_heads, use_gdn_forget_gate=True):
        super().__init__()
        self.d_model = d_model
        self.d_mem = d_mem
        self.n_heads = n_heads
        
        assert d_mem % n_heads == 0, f"d_mem ({d_mem}) must be divisible by n_heads ({n_heads})"
        
        self.use_gdn_forget_gate = use_gdn_forget_gate
        self.nu = 3
        self.d_key = 2 * self.nu * d_mem  # DPFP expands dimension
        
        # Learnable forget gate decay parameter (like GDN's A_log)
        self.A_log = nn.Parameter(torch.log(torch.rand(n_heads) + 1e-6))
        self.dt_bias = nn.Parameter(torch.zeros(n_heads))
        
        # Forget gate projection (optional, for per-token gating)
        # Note: mem_tokens have d_model dimension, not d_mem
        self.W_g = nn.Linear(d_model, n_heads, bias=False)
        
    def forward(self, W_mem, z, mem_tokens, W_mk, W_mv, W_mb, phi, use_denom=True):
        """
        Apply GDN update rule to memory.
        
        Args:
            W_mem: [1, n_heads, d_key, d_model] - current memory state
            z: [1, n_heads, d_key] - denominator accumulator (if use_denom)
            mem_tokens: [B, num_mem, d_mem] - memory tokens to write with
            W_mk: Linear projection to keys
            W_mv: Linear projection to values  
            W_mb: Linear projection to update gate (beta)
            phi: Feature mapping (DPFP)
            use_denom: Whether to use denominator normalization
            
        Returns:
            W_mem_updated: Updated memory state
            z_updated: Updated denominator (if use_denom)
        """
        bsz, num_mem, d_mem = mem_tokens.shape
        
        # Project memory tokens
        k = W_mk(mem_tokens)  # [B, num_mem, d_mem]
        v = W_mv(mem_tokens)  # [B, num_mem, d_model]
        beta = W_mb(mem_tokens).sigmoid()  # [B, num_mem, d_model] or [B, num_mem, n_heads]
        
        # L2 normalize keys (GDN style)
        k = F.normalize(k, dim=-1, p=2.0)
        
        # Apply feature mapping to keys
        mk = phi(k)  # [B, num_mem, 2 * nu * d_mem]
        mk = F.normalize(mk, dim=-1, p=2.0)
        
        # Convert to head format
        mk_heads = mk.view(bsz, num_mem, self.n_heads, self.d_key // self.n_heads)
        mk_heads = mk_heads.permute(0, 2, 1, 3)  # [B, n_heads, num_mem, d_key/n_heads]
        
        v_heads = v.view(bsz, num_mem, self.n_heads, self.d_model // self.n_heads)
        v_heads = v_heads.permute(0, 2, 1, 3)  # [B, n_heads, num_mem, d_model/n_heads]
        
        # Handle beta gate shape
        if beta.dim() == 3:  # [B, num_mem, d_model]
            beta_heads = beta.view(bsz, num_mem, self.n_heads, self.d_model // self.n_heads)
            beta_heads = beta_heads.permute(0, 2, 1, 3)  # [B, n_heads, num_mem, d_model/n_heads]
        else:  # [B, num_mem, n_heads]
            beta_heads = beta.unsqueeze(-1).expand(-1, -1, -1, self.d_model // self.n_heads)
            beta_heads = beta_heads.permute(0, 2, 1, 3)
        
        # ========== GDN UPDATE ==========
        
        # 1. Forget gate decay (apply to entire memory)
        if self.use_gdn_forget_gate:
            # Compute forget gate from memory tokens (aggregate over positions)
            g_raw = self.W_g(mem_tokens)  # [B, num_mem, n_heads]
            g_decay = -torch.exp(self.A_log) * F.softplus(g_raw + self.dt_bias)
            # Aggregate over memory token positions and batch: [n_heads]
            g_decay = g_decay.mean(dim=(0, 1))  # [n_heads]
            g_decay = g_decay.unsqueeze(-1).unsqueeze(-1).unsqueeze(0)  # [1, n_heads, 1, 1]
            
            # Apply exponential decay to memory
            W_mem_decayed = W_mem * torch.exp(g_decay)
        else:
            W_mem_decayed = W_mem
        
        # 2. Accumulate updates over all memory token positions
        associations = torch.zeros_like(W_mem_decayed)
        
        for pos in range(num_mem):
            mk_pos = mk_heads[:, :, pos, :]  # [B, n_heads, d_key/n_heads]
            v_pos = v_heads[:, :, pos, :]    # [B, n_heads, d_model/n_heads]
            beta_pos = beta_heads[:, :, pos, :]  # [B, n_heads, d_model/n_heads]
            
            # Compute residual: v - (W_mem @ k^T)
            # What's already reconstructed by this key
            # W_mem: [1, n_heads, d_key/n_heads, d_model/n_heads]
            # mk_pos: [B, n_heads, d_key/n_heads]
            # Use batched einsum without expanding W_mem
            v_reconstructed = torch.einsum('bhk,hkv->bhv', mk_pos, W_mem_decayed[0])
            v_residual = v_pos - v_reconstructed
            
            # Apply update gate
            v_residual = v_residual * beta_pos
            
            # Rank-1 update: k * v_residual
            assoc_pos = mk_pos.unsqueeze(-1) * v_residual.unsqueeze(-2)
            associations = associations + assoc_pos
        
        # 3. Final update - average associations over batch
        W_mem_updated = W_mem_decayed + associations.mean(dim=0, keepdim=True)
        
        # 4. Update denominator if using normalization
        if use_denom:
            # Aggregate mk over memory token positions and batch
            # mk_heads: [B, n_heads, num_mem, d_key/n_heads]
            mk_agg = mk_heads.mean(dim=(0, 2))  # [n_heads, d_key/n_heads]
            # Apply beta scaling (aggregate beta over positions)  
            beta_agg = beta_heads.mean(dim=(0, 2))  # [n_heads, d_model/n_heads]
            # Weight mk by beta and sum over value dimension
            # Result: [1, n_heads, d_key/n_heads]
            beta_sum = beta_agg.sum(dim=-1, keepdim=True)  # [n_heads, 1]
            z_update = (mk_agg * beta_sum).unsqueeze(0)  # [1, n_heads, d_key/n_heads]
            z_updated = z + z_update
        else:
            z_updated = z
        
        return W_mem_updated, z_updated


# === Associative Layer with GDN Update ===

class AssociativeLayerWrapperGDN(nn.Module):
    """
    ARMT layer wrapper with GDN update rule.
    
    Key differences from original ARMT:
    - Uses GDN's gated delta update instead of simple delta update
    - Applies forget gate decay before each update
    - Uses L2 normalization on keys (like GDN)
    - Accumulates rank-1 updates over memory token positions
    """
    
    def __init__(self, layer, d_model, num_mem_tokens, d_mem, n_heads=1, 
                 correction=True, use_denom=True, use_gdn_forget_gate=True):
        super().__init__()
        
        self.d_model = d_model
        self.num_mem_tokens = num_mem_tokens
        self.d_mem = d_mem
        self.n_heads = n_heads
        self.correction = correction
        self.use_denom = use_denom
        
        # Get dtype from layer
        layer_dtype = next(layer.parameters()).dtype
        
        # Projections for memory operations
        self.W_mq = nn.Linear(d_model, d_mem, bias=False, dtype=layer_dtype)
        self.W_mk = nn.Linear(d_model, d_mem, bias=False, dtype=layer_dtype)
        self.W_mv = nn.Linear(d_model, d_model, bias=False, dtype=layer_dtype)
        self.W_mb = nn.Linear(d_model, d_model, dtype=layer_dtype)  # update gate (beta)
        
        # Zero initialize output projection
        torch.nn.init.zeros_(self.W_mv.weight)
        s = 1 / math.sqrt(d_model)
        
        # Feature mapping
        self.phi = DPFP(nu=3)
        self.d_key = 2 * 3 * d_mem  # DPFP expansion
        
        # GDN update rule
        self.gdn_update = GDNUpdateRule(
            d_model=d_model,
            d_mem=d_mem,
            n_heads=n_heads,
            use_gdn_forget_gate=use_gdn_forget_gate
        )
        
        self.layer = layer
        self.generate_mode = False
        self.first_seg = True
        
        # Initialize memory
        self.zero_mem()
    
    def _to_heads(self, x):
        """Reshape to [B, n_heads, seq_len, d_head]"""
        bsz, seq_len, d_model = x.shape
        x = x.reshape(bsz, seq_len, self.n_heads, d_model // self.n_heads)
        x = x.permute(0, 2, 1, 3)
        return x
    
    def _from_heads(self, x):
        """Reshape from [B, n_heads, seq_len, d_head] to [B, seq_len, d_model]"""
        bsz, n_heads, seq_len, d_head = x.shape
        x = x.permute(0, 2, 1, 3).reshape(bsz, seq_len, n_heads * d_head)
        return x
    
    def associate(self, hidden_states):
        """Read from associative memory"""
        bsz, seq_len, d_model = hidden_states.shape

        self.W_mem = self.W_mem.to(hidden_states.device)
        if self.use_denom:
            self.z = self.z.to(hidden_states.device)

        q = self._to_heads(self.W_mq(hidden_states))
        mq = self.phi(q) # (bsz, n_heads, seq_len, 2 * d_head * nu)
        mq = F.normalize(mq, dim=-1, p=2.0)
        
        # Debug shapes
        # print(f'DEBUG associate: mq.shape={mq.shape}, W_mem.shape={self.W_mem.shape}, z.shape={self.z.shape}')
        
        num = torch.einsum('ihjk,ihkt->ihjt', mq, self.W_mem)
        if self.use_denom:
            # self.z: [1, n_heads, d_key/n_heads], mq: [B, n_heads, seq_len, d_key/n_heads]
            # Contract over key dimension 'k', keeping batch, heads, seq_len
            z_squeezed = self.z[0]  # [n_heads, d_key/n_heads]
            denom = torch.einsum("hk,bhjk->bhj", z_squeezed, mq)[..., None] + 1e-5
            hidden_states = num / denom # (bsz, n_heads, seq_len, d_model // n_heads)
        else:
            hidden_states = num
        hidden_states = self._from_heads(hidden_states)
        return hidden_states
    
    def forward(self, hidden_states, *args, **kwargs):
        """Forward pass with memory read and write"""
        # Read from memory (if not first segment)
        if not self.first_seg:
            hidden_states = self.associate(hidden_states) + hidden_states
        
        # Process through backbone layer
        out = self.layer(hidden_states, *args, **kwargs)
        
        # Write to memory (if not in generate mode)
        if not self.generate_mode:
            # Extract memory tokens from layer output
            if isinstance(out, tuple):
                mem_tokens = out[0][:, -self.num_mem_tokens:]
            else:
                mem_tokens = out[:, -self.num_mem_tokens:]
            
            self.update_mem(mem_tokens)
        
        return out
    
    def forward_no_update(self, hidden_states, *args, **kwargs):
        """Forward without writing to memory (for ACT)"""
        if not self.first_seg:
            hidden_states = self.associate(hidden_states) + hidden_states
        out = self.layer(hidden_states, *args, **kwargs)
        return out
    
    def update_mem(self, mem_tokens):
        """
        Update memory using GDN rule.
        
        Args:
            mem_tokens: [B, num_mem, d_mem] - memory tokens from layer output
        """
        device = mem_tokens.device
        
        # Move memory to device
        self.W_mem = self.W_mem.to(device)
        if self.use_denom:
            self.z = self.z.to(device)
        
        # Apply GDN update rule
        self.W_mem, self.z = self.gdn_update(
            W_mem=self.W_mem,
            z=self.z,
            mem_tokens=mem_tokens,
            W_mk=self.W_mk,
            W_mv=self.W_mv,
            W_mb=self.W_mb,
            phi=self.phi,
            use_denom=self.use_denom
        )
        
        self.first_seg = False
    
    def freeze_mem(self):
        """Freeze memory parameters"""
        for param in self.W_mb.parameters():
            param.requires_grad = False
        for param in self.W_mq.parameters():
            param.requires_grad = False
        for param in self.W_mk.parameters():
            param.requires_grad = False
        for param in self.W_mv.parameters():
            param.requires_grad = False
        for param in self.gdn_update.parameters():
            param.requires_grad = False
    
    def zero_mem(self):
        """Reset memory to initial state"""
        self.first_seg = True
        layer_dtype = next(self.layer.parameters()).dtype
        
        # Initialize memory state
        self.W_mem = torch.zeros(1, self.n_heads, self.d_key // self.n_heads, 
                                 self.d_model // self.n_heads, dtype=layer_dtype)
        self.W_mem.requires_grad_(False)
        
        # Initialize denominator
        if self.use_denom:
            self.z = torch.zeros(1, self.n_heads, self.d_key // self.n_heads, 
                                dtype=layer_dtype)
            self.z.requires_grad_(False)
    
    def detach_mem(self):
        """Detach memory from computation graph"""
        self.W_mem = self.W_mem.detach()
        if self.use_denom:
            self.z = self.z.detach()


# === Adaptive Version with ACT ===

class AdaptiveAssociativeLayerWrapperGDN(AssociativeLayerWrapperGDN):
    """GDN wrapper with ACT for recurrent refinement"""
    
    def __init__(self, layer, d_model, num_mem_tokens, d_mem, max_hop, 
                 n_heads=1, correction=True, use_denom=True, 
                 use_gdn_forget_gate=True, constant_depth=False):
        super().__init__(layer, d_model, num_mem_tokens, d_mem, n_heads, 
                        correction, use_denom, use_gdn_forget_gate)
        
        self.act = ACT_basic(d_model) if not constant_depth else None
        self.depth = max_hop
        self.max_length = 1024
        
        self.timing_signal = gen_timing_signal(self.max_length, d_model)
        self.position_signal = gen_timing_signal(self.depth, d_model)
        
        self.remainders = torch.zeros(1,)
        self.n_updates = torch.zeros(1,)
        self.segments_passed = torch.zeros(1,)
    
    def associate(self, hidden_states):
        """Read from memory with ACT refinement"""
        device = hidden_states.device
        self.remainders = self.remainders.to(device)
        self.n_updates = self.n_updates.to(device)
        self.segments_passed = self.segments_passed.to(device)
        
        out, (remainders, n_updates) = self.act(
            state=hidden_states,
            inputs=hidden_states,
            fn=super().associate,
            time_enc=self.timing_signal,
            pos_enc=self.position_signal,
            max_hop=self.depth
        )
        
        self.remainders = self.remainders + remainders.mean()
        self.n_updates = self.n_updates + n_updates.mean()
        self.segments_passed = self.segments_passed + 1
        return out
    
    def zero_mem(self):
        """Reset memory and ACT state"""
        self.remainders = torch.zeros(1,)
        self.n_updates = torch.zeros(1,)
        self.segments_passed = torch.zeros(1,)
        super().zero_mem()
    
    def detach_mem(self):
        """Detach memory and reset ACT state"""
        self.remainders = torch.zeros(1,)
        self.n_updates = torch.zeros(1,)
        self.segments_passed = torch.zeros(1,)
        super().detach_mem()


# === Memory Cell Wrapper ===

class AssociativeMemoryCellGDN(nn.Module):
    """
    Wraps a base model with GDN-based associative memory.
    
    Similar to ARMT's AssociativeMemoryCell but uses GDN update rule.
    """
    
    def __init__(self, base_model, num_mem_tokens, d_mem,
                 layers_attr='model.layers', wrap_pos=False, correction=True,
                 n_heads=1, use_denom=True, use_gdn_forget_gate=True,
                 freeze_mem=False, act_on=False, max_hop=4, act_type='layer',
                 constant_depth=False, **rmt_config):
        super().__init__()
        
        self.model = base_model
        self.num_mem_tokens = num_mem_tokens
        self.d_mem = d_mem
        self.d_model = base_model.get_input_embeddings().embedding_dim
        self.use_denom = use_denom
        self.use_gdn_forget_gate = use_gdn_forget_gate
        self.constant_depth = constant_depth
        
        # Auto-detect layers attribute based on model type
        model_type = base_model.config.model_type
        if model_type == 'gpt2':
            layers_attr = 'transformer.h'
        elif model_type in ('llama', 'mamba', 'mamba2'):
            layers_attr = 'model.layers'
        
        layers_attrs = layers_attr.split('.')
        def _get_layers_from_model(model_root):
            layers_obj = model_root
            for attr in layers_attrs:
                layers_obj = getattr(layers_obj, attr)
            return layers_obj
        
        layers = _get_layers_from_model(self.model)
        
        # Wrap each layer
        for i in range(len(layers)):
            kw = dict(
                layer=layers[i],
                d_model=self.d_model,
                num_mem_tokens=self.num_mem_tokens,
                d_mem=self.d_mem,
                n_heads=n_heads,
                correction=correction,
                use_denom=use_denom,
                use_gdn_forget_gate=use_gdn_forget_gate,
            )
            
            if act_on and act_type == 'layer':
                kw['max_hop'] = max_hop
                kw['constant_depth'] = constant_depth
                layers[i] = AdaptiveAssociativeLayerWrapperGDN(**kw)
            else:
                layers[i] = AssociativeLayerWrapperGDN(**kw)
        
        self.get_layers = lambda: _get_layers_from_model(self.model)
        self.act_on = act_on
        
        # Create memory tokens
        self.create_memory(num_mem_tokens)
        
        if wrap_pos:
            self.wrap_pos = True
            self.wrap_positional_embeddings(num_mem_tokens)
        else:
            self.wrap_pos = False
        
        if freeze_mem:
            for layer in self.get_layers():
                layer.freeze_mem()
    
    def generate_mode(self, is_on):
        """Set generate mode for all layers"""
        for layer in self.get_layers():
            layer.generate_mode = is_on
    
    def create_memory(self, num_mem_tokens):
        """Create learnable memory tokens"""
        self.num_mem_tokens = num_mem_tokens
        embeddings = self.model.get_input_embeddings()
        memory_dim = getattr(self.model.config, 'n_embd', 
                            self.model.config.hidden_size)
        
        memory_weights = torch.randn((num_mem_tokens, memory_dim),
                                    device=embeddings.weight.data.device,
                                    dtype=embeddings.weight.data.dtype) * embeddings.weight.data.std()
        
        self.register_parameter('memory', 
                               nn.Parameter(memory_weights, requires_grad=True))
    
    def wrap_positional_embeddings(self, num_mem_tokens):
        """Wrap positional embeddings to accommodate memory tokens"""
        num_pos_embs, emb_dim = self.model.transformer.wpe.weight.shape
        prev_embs = self.model.transformer.wpe.weight.detach()
        
        self.model.transformer.wpe = nn.Embedding(num_mem_tokens + num_pos_embs, emb_dim)
        
        with torch.no_grad():
            self.model.transformer.wpe.weight[:len(prev_embs)] = prev_embs
        
        new_num_pos = num_pos_embs + num_mem_tokens
        for layer in self.model.transformer.h:
            layer.layer.attn.bias = torch.tril(
                torch.ones((new_num_pos, new_num_pos), dtype=torch.uint8)
            ).view(1, 1, new_num_pos, new_num_pos)
    
    def set_memory(self, input_shape):
        """Repeat memory tokens for batch"""
        memory = self.memory.repeat(input_shape[0], 1, 1)
        return memory, None
    
    def zero_mem(self):
        """Reset all layer memories"""
        for layer in self.get_layers():
            layer.zero_mem()
    
    def detach_mem(self):
        """Detach all layer memories"""
        for layer in self.get_layers():
            layer.detach_mem()
    
    def forward(self, input_ids, labels=None, labels_mask=None, 
                zero_mem=False, attention_mask=None, **kwargs):
        """Forward pass"""
        if zero_mem:
            self.zero_mem()
        
        seg_kwargs = self.process_input(input_ids, **kwargs)
        out = self.model(**seg_kwargs)
        out = self.process_output(out, labels, labels_mask)
        return out
    
    def process_input(self, input_ids, **kwargs):
        """Prepare inputs with memory tokens"""
        memory_state, sink = self.set_memory(input_ids.shape)
        seg_kwargs = dict(**kwargs)
        
        inputs_embeds = kwargs.get('inputs_embeds')
        if inputs_embeds is None:
            inputs_embeds = self.model.get_input_embeddings()(input_ids)
        
        # Concatenate memory tokens at the end
        inputs_embeds = torch.cat([inputs_embeds, memory_state], dim=1)
        
        seg_kwargs['input_ids'] = None
        seg_kwargs['inputs_embeds'] = inputs_embeds
        
        if kwargs.get('attention_mask') is not None:
            seg_kwargs['attention_mask'] = self.pad_attention_mask(
                kwargs['attention_mask'], dtype=inputs_embeds.dtype
            )
        
        seg_kwargs['output_hidden_states'] = True
        return seg_kwargs
    
    def pad_attention_mask(self, attention_mask, dtype=float):
        """Pad attention mask for memory tokens"""
        if self.num_mem_tokens in {0, None}:
            return attention_mask
        
        shape = list(attention_mask.shape)
        if len(shape) == 4:
            shape[-1] += self.num_mem_tokens
            shape[-2] += self.num_mem_tokens
            mask = torch.ones(*shape, dtype=dtype).to(attention_mask.device)
            mask[..., :-self.num_mem_tokens, :-self.num_mem_tokens] = attention_mask
            mask[..., :-self.num_mem_tokens, -self.num_mem_tokens:] = 0
            
            # Invert mask for causal attention
            if not os.environ.get("NOT_INVERT_ATTN_MASK"):
                min_dtype = torch.finfo(dtype).min
                mask = (1.0 - mask) * min_dtype
        else:
            shape[-1] += self.num_mem_tokens
            mask = torch.ones(*shape, dtype=dtype).to(attention_mask.device)
            mask[..., :-self.num_mem_tokens] = attention_mask
        
        return mask.to(dtype)
    
    def process_output(self, model_outputs, labels, labels_mask, **kwargs):
        """Process outputs, removing memory tokens"""
        if self.num_mem_tokens not in {0, None}:
            out = CausalLMOutputWithCrossAttentions()
            out['logits'] = model_outputs.logits[:, :-self.num_mem_tokens]
            
            if kwargs.get('output_hidden_states'):
                out['hidden_states'] = [
                    lh[:, :-self.num_mem_tokens] 
                    for lh in model_outputs.hidden_states
                ]
            if kwargs.get('output_attentions'):
                out['attentions'] = model_outputs['attentions']
        else:
            out = model_outputs
        
        # Compute loss
        if labels is not None:
            logits = out['logits'][..., :-1, :].contiguous()
            flat_logits = logits.view(-1, logits.size(-1))
            labels = labels[..., 1:].contiguous()
            flat_labels = labels.view(-1)
            
            if labels_mask is not None:
                flat_mask = labels_mask[..., :-1].contiguous().view(-1)
                flat_logits = flat_logits[flat_mask]
                flat_labels = flat_labels[flat_mask]
            
            ce_loss_fn = nn.CrossEntropyLoss(reduction='sum')
            ce_loss = ce_loss_fn(flat_logits, flat_labels)
            
            if labels_mask is not None:
                denom = labels_mask[..., :-1].contiguous().view(-1).sum()
            else:
                denom = (flat_labels != -100).sum()
            denom = torch.clamp(denom, min=1)
            loss = ce_loss / denom
            out['ce_loss'] = loss
            out['loss'] = loss  # HF Trainer expects 'loss' key
        
        return out
    
    def generate(self, input_ids, attention_mask, zero_mem=False, **generate_kwargs):
        """Generate with memory"""
        if zero_mem:
            self.zero_mem()
        
        self.generate_mode(True)
        seg_kwargs = self.process_input(input_ids, attention_mask=attention_mask)
        
        out = self.model.generate(
            inputs_embeds=seg_kwargs['inputs_embeds'][:, :-self.num_mem_tokens],
            attention_mask=seg_kwargs['attention_mask'][:, :-self.num_mem_tokens],
            **generate_kwargs
        )
        
        self.generate_mode(False)
        return out


# === HuggingFace Model Wrapper ===

class ARMTGDNForCausalLM(nn.Module):
    """
    HuggingFace-compatible model wrapper for ARMT with GDN update.
    """
    
    def __init__(self, base_model, num_mem_tokens, d_mem, 
                 n_heads=1, correction=True, use_denom=True,
                 use_gdn_forget_gate=True, act_on=False, max_hop=4,
                 act_type='layer', constant_depth=False):
        super().__init__()
        
        self.armt_cell = AssociativeMemoryCellGDN(
            base_model=base_model,
            num_mem_tokens=num_mem_tokens,
            d_mem=d_mem,
            n_heads=n_heads,
            correction=correction,
            use_denom=use_denom,
            use_gdn_forget_gate=use_gdn_forget_gate,
            act_on=act_on,
            max_hop=max_hop,
            act_type=act_type,
            constant_depth=constant_depth
        )
        
        self.config = base_model.config
    
    def forward(self, input_ids=None, labels=None, labels_mask=None, 
                attention_mask=None, zero_mem=False, segments=None, **kwargs):
        """Forward pass - compatible with HF Trainer"""
        # Handle HF Trainer calling convention (inputs as dict)
        if input_ids is None and 'input_ids' in kwargs:
            input_ids = kwargs.pop('input_ids')
        
        # For ARMT-GDN, we use segments format from collate_fn
        if segments is not None:
            # Concatenate segments for forward pass
            seg0 = segments[0]  # context segment
            seg1 = segments[1]  # query+target segment
            
            # Process first segment (context) - no loss
            self.armt_cell.zero_mem()
            out0 = self.armt_cell(
                input_ids=seg0['input_ids'],
                attention_mask=seg0.get('attention_mask'),
                zero_mem=False,
            )
            
            # Process second segment (query+target) - with loss
            out1 = self.armt_cell(
                input_ids=seg1['input_ids'],
                labels=seg1.get('labels'),
                labels_mask=seg1.get('labels_mask'),
                attention_mask=seg1.get('attention_mask'),
                zero_mem=False,
            )
            
            # Return combined output
            return out1
        
        if input_ids is None:
            # Try to get from kwargs with different keys
            input_ids = kwargs.get('input_ids') or kwargs.get('inputs')
        
        if input_ids is None:
            raise ValueError("input_ids must be provided")
        
        return self.armt_cell(
            input_ids=input_ids,
            labels=labels,
            labels_mask=labels_mask,
            attention_mask=attention_mask,
            zero_mem=zero_mem,
            **kwargs
        )
    
    def generate(self, input_ids, attention_mask=None, **kwargs):
        """Generate"""
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)
        return self.armt_cell.generate(input_ids, attention_mask, **kwargs)
    
    def zero_mem(self):
        """Reset memory"""
        self.armt_cell.zero_mem()
    
    def detach_mem(self):
        """Detach memory"""
        self.armt_cell.detach_mem()
