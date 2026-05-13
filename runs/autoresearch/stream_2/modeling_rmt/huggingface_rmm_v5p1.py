"""v5p1: v5p with the orthogonal-rotation knob removed from the default path.

Changes vs. v5p:
  * `use_orthogonal_rotation` config flag, default False. When False the layer
    skips the per-fwd QR-on-skew-matrix entirely (the rotation is replaced by
    identity). Keeps the original code path as an ablation when set True.
  * Block-diagonal causal mask is built once per (S, T, device, dtype) and
    cached on the cell — no per-step Python for-loop.

Rationale: the rotation is off-axis for the capacity-bottleneck story (it
adds a learnable transform around GDN unrelated to state size / write
mechanism) and breaks the S=1 reduction RMCA-GDN → GDN. Default off so the
S=1 endpoint is clean; flag retained for ablation.

Parallel-prefill semantics are unchanged from v5p:
  * S context segments processed in one fwd via block-diag masked attention.
  * GDN runs once over all S*M write vectors.
  * WRITE → GDN → READ → ATTN inside each layer (writes taken from PRE-attn
    tokens — a one-step phase shift of v5's recurrent ATTN-then-WRITE order).
  * qt segment runs through the recurrent path, byte-identical to v5.
"""
from __future__ import annotations

import inspect
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

from transformers import PreTrainedModel, PretrainedConfig
from transformers.modeling_outputs import CausalLMOutputWithCrossAttentions

import fla.layers
from fla.models.utils import Cache


# ───────────────────────── orthogonal rotation ──────────────────────────────
class OrthogonalRotation(nn.Module):
    def __init__(self, state_size: int = 32):
        super().__init__()
        self.state_size = state_size
        skew_init = torch.zeros(state_size, state_size)
        for i in range(state_size):
            for j in range(i + 1, state_size):
                skew_init[i, j] = torch.randn(1) * 0.01
                skew_init[j, i] = -skew_init[i, j]
        self.skew_matrix = nn.Parameter(skew_init)

    def _orthogonalize(self, A: torch.Tensor) -> torch.Tensor:
        Q, R = torch.linalg.qr(A)
        d = torch.diag(R)
        signs = torch.sign(d)
        return Q * signs.unsqueeze(0)

    def forward(self, x: torch.Tensor, inverse: bool = False) -> torch.Tensor:
        I = torch.eye(self.state_size, device=self.skew_matrix.device, dtype=self.skew_matrix.dtype)
        Q = self._orthogonalize(I + self.skew_matrix)
        if inverse:
            Q = Q.t()
        return torch.matmul(x, Q)


class _IdentityRotation(nn.Module):
    """No-op stand-in for OrthogonalRotation (preserves `inverse` kwarg signature)."""

    def forward(self, x: torch.Tensor, inverse: bool = False) -> torch.Tensor:
        return x


class RecurrentLayerWithSkip(nn.Module):
    def __init__(self, original_layer: nn.Module):
        super().__init__()
        self.layer = original_layer

    def forward(self, hidden_states, *args, **kwargs):
        output = self.layer(hidden_states, *args, **kwargs)
        out_tensor = output[0] if isinstance(output, tuple) else output
        if isinstance(output, tuple):
            return (hidden_states + out_tensor,) + output[1:]
        return hidden_states + out_tensor


# ───────────────────────── cross-attention helpers ──────────────────────────
class LlamaCrossAttention(nn.Module):
    def __init__(self, hidden_size, num_heads, kv_hidden_size=None, head_dim=None,
                 dropout=0.0, bias=False, out_hidden_size=None):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = head_dim if head_dim is not None else hidden_size // num_heads
        self.scaling = self.head_dim ** -0.5
        self.attention_dropout = dropout
        kv_hidden_size = kv_hidden_size or hidden_size
        self.q_proj = nn.Linear(hidden_size, num_heads * self.head_dim, bias=bias)
        self.k_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.v_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.o_proj = nn.Linear(num_heads * self.head_dim, out_hidden_size or hidden_size, bias=bias)

    def forward(self, from_states, to_states, attention_mask=None):
        B, Q_len, _ = from_states.shape
        K_len = to_states.shape[1]
        q = self.q_proj(from_states).view(B, Q_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(to_states).view(B, K_len, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(to_states).view(B, K_len, self.num_heads, self.head_dim).transpose(1, 2)
        w = torch.matmul(q, k.transpose(-2, -1)) * self.scaling
        if attention_mask is not None:
            w = w + attention_mask
        w = F.softmax(w, dim=-1, dtype=torch.float32).to(q.dtype)
        if self.training and self.attention_dropout > 0:
            w = F.dropout(w, p=self.attention_dropout)
        out = torch.matmul(w, v).transpose(1, 2).reshape(B, Q_len, -1).contiguous()
        return self.o_proj(out), w


# ───────────────────────── memory writer / reader ───────────────────────────
class MemoryWriter(nn.Module):
    """Pool/cross_attn writer. parallel(...) handles S segments at once with a mask."""

    def __init__(self, hidden_size, num_vectors, mode='cross_attn', write_value_dim=None, bias=False):
        super().__init__()
        if mode not in ('pool', 'cross_attn'):
            raise ValueError(f"MemoryWriter mode must be 'pool' or 'cross_attn', got '{mode}'")
        self.mode = mode
        self.num_vectors = num_vectors
        self.hidden_size = hidden_size
        self.write_value_dim = write_value_dim or hidden_size
        self.scaling = hidden_size ** -0.5

        self.write_queries = nn.Parameter(torch.zeros(num_vectors, hidden_size))
        nn.init.normal_(self.write_queries, std=hidden_size ** -0.5)
        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
        self.v_proj = nn.Linear(hidden_size, self.write_value_dim, bias=bias)
        if mode == 'cross_attn':
            self.q_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
            self.out_proj = nn.Linear(self.write_value_dim, self.write_value_dim, bias=bias)

    def forward(self, hidden_states):
        """Recurrent path: (B, T, d) -> (B, M, d_v)"""
        B = hidden_states.shape[0]
        queries = self.write_queries.unsqueeze(0).expand(B, -1, -1)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)
        k = self.k_proj(hidden_states)
        v = self.v_proj(hidden_states)
        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)
        if self.mode == 'cross_attn':
            out = self.out_proj(out)
        return out

    def parallel(self, hidden_states, S, T, M):
        """(B, S*T, d) -> (B, S*M, d_v). Block-diagonal: query group i ↔ tokens [i*T:(i+1)*T]."""
        B = hidden_states.shape[0]
        d = self.hidden_size
        # (B, S, M, d) queries — same M learnable queries reused across S segments
        queries = self.write_queries.view(1, 1, M, d).expand(B, S, M, d)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)
        # Tokens reshaped per segment: (B, S, T, d)
        tokens = hidden_states.view(B, S, T, d)
        k = self.k_proj(tokens)                                    # (B, S, T, d)
        v = self.v_proj(tokens)                                    # (B, S, T, d_v)
        # Per-segment softmax-attn: queries attend only to that segment's tokens
        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling   # (B, S, M, T)
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)                                # (B, S, M, d_v)
        if self.mode == 'cross_attn':
            out = self.out_proj(out)
        return out.reshape(B, S * M, self.write_value_dim)


class MemoryReader(nn.Module):
    """unpool/cross_attn reader."""

    def __init__(self, hidden_size, write_value_dim, mode='cross_attn', num_heads=1, bias=False):
        super().__init__()
        if mode not in ('unpool', 'cross_attn'):
            raise ValueError(f"MemoryReader mode must be 'unpool' or 'cross_attn', got '{mode}'")
        self.mode = mode
        self.hidden_size = hidden_size
        self.scaling = hidden_size ** -0.5
        if mode == 'unpool':
            self.k_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
            self.v_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
        else:
            self.cross_attn = LlamaCrossAttention(
                hidden_size=hidden_size, num_heads=num_heads,
                kv_hidden_size=write_value_dim, out_hidden_size=hidden_size,
            )

    def forward(self, token_states, memory_states):
        """Recurrent: (B, T, d), (B, M, d_v) -> (B, T, d)"""
        if self.mode == 'unpool':
            k = self.k_proj(memory_states)
            v = self.v_proj(memory_states)
            attn = torch.matmul(token_states, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            return torch.matmul(attn, v)
        out, _ = self.cross_attn(from_states=token_states, to_states=memory_states)
        return out

    def parallel(self, token_states, mem_shifted, S, T, M):
        """Each segment's T tokens attend to the corresponding M-block in mem_shifted.

        token_states: (B, S*T, d)
        mem_shifted:  (B, S*M, d_v)   -- mem_shifted[:, i*M:(i+1)*M] = mem_{i-1} (zeros for i=0)
        returns:      (B, S*T, d)
        """
        B = token_states.shape[0]
        d = self.hidden_size
        tokens = token_states.view(B, S, T, d)
        if self.mode == 'unpool':
            mem = mem_shifted.view(B, S, M, -1)
            k = self.k_proj(mem)                                  # (B, S, M, d)
            v = self.v_proj(mem)                                  # (B, S, M, d)
            attn = torch.matmul(tokens, k.transpose(-1, -2)) * self.scaling   # (B, S, T, M)
            attn = F.softmax(attn, dim=-1)
            out = torch.matmul(attn, v)                           # (B, S, T, d)
            return out.reshape(B, S * T, d)
        # cross_attn: reuse LlamaCrossAttention per-segment via reshape into batch
        d_v = mem_shifted.shape[-1]
        from_states = tokens.reshape(B * S, T, d)
        to_states = mem_shifted.view(B, S, M, d_v).reshape(B * S, M, d_v)
        out, _ = self.cross_attn(from_states=from_states, to_states=to_states)
        return out.view(B, S * T, d)


# ───────────────────────── per-layer wrapper ────────────────────────────────
class RecurrentMemoryLayerWrapper(nn.Module):
    """v5p layer: parallel-prefill path + faithful v5 recurrent path.

    Parallel-mode args are stashed by RecurrentMemoryCell.parallel_forward before
    invoking the base model so the wrapper's forward can branch.
    """

    def __init__(self, base_layer, fla_layer, model_hidden_size,
                 num_memory_vectors=1, write_mode='cross_attn', read_mode='cross_attn',
                 write_value_dim=None, num_memory_heads=1, write_residual=False,
                 use_orthogonal_rotation=False):
        super().__init__()
        if write_mode == 'identity' and read_mode != 'identity':
            raise ValueError("identity write_mode must be paired with identity read_mode")
        write_value_dim_resolved = write_value_dim or model_hidden_size
        if read_mode == 'identity' and write_value_dim_resolved != model_hidden_size:
            raise ValueError("read_mode='identity' requires write_value_dim == model_hidden_size")

        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.write_residual = write_residual
        self.num_memory_vectors = num_memory_vectors
        self.write_value_dim = write_value_dim_resolved

        self.write_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)
        self.read_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)

        if write_mode == 'identity':
            self.fla_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)
        else:
            self.memory_writer = MemoryWriter(
                hidden_size=model_hidden_size, num_vectors=num_memory_vectors,
                mode=write_mode, write_value_dim=self.write_value_dim,
            )
            if read_mode in ('unpool', 'cross_attn'):
                self.memory_reader = MemoryReader(
                    hidden_size=model_hidden_size, write_value_dim=self.write_value_dim,
                    mode=read_mode, num_heads=num_memory_heads,
                )

        self.cache = Cache()
        self.last_write_output: torch.Tensor | None = None

        self.state_size = fla_layer.state_size if hasattr(fla_layer, 'state_size') else 128
        self.use_orthogonal_rotation = use_orthogonal_rotation
        self.orthogonal_rotation = (
            OrthogonalRotation(state_size=self.state_size)
            if use_orthogonal_rotation else _IdentityRotation()
        )

        # Parallel-mode stash (set by parent cell during parallel_forward)
        self.parallel_mode = False
        self._p_S = self._p_T = self._p_M = 0
        self._p_attn_mask = None

    # ───── recurrent helpers (faithful v5) ─────
    def _gdn_recurrent(self, x, attention_mask):
        fla_out = self.fla_layer(
            x, attention_mask=attention_mask,
            past_key_values=self.cache, use_cache=True,
        )
        return fla_out[0], fla_out[2]

    def forward(self, hidden_states, *args, **kwargs):
        if self.parallel_mode:
            return self._forward_parallel(hidden_states, *args, **kwargs)
        return self._forward_recurrent(hidden_states, *args, **kwargs)

    # ───── recurrent path (v5 semantics, simplified — drops dead dual_state) ─
    def _forward_recurrent(self, hidden_states, *args, **kwargs):
        attention_mask = kwargs.get('attention_mask')

        # 1. READ
        if self.read_mode in ('unpool', 'cross_attn') and self.last_write_output is not None:
            hidden_states = hidden_states + self.memory_reader(
                self.read_norm(hidden_states), self.last_write_output
            )

        # 2. base layer
        output = self.base_layer(hidden_states, *args, **kwargs)
        hidden_states = output[0] if isinstance(output, tuple) else output

        # 3. WRITE
        if self.write_mode == 'identity':
            x = self.fla_norm(hidden_states)
            x_rot = self.orthogonal_rotation(x)
            fla_out, new_cache = self._gdn_recurrent(x_rot, attention_mask)
            fla_out = self.orthogonal_rotation(fla_out, inverse=True)
            hidden_states = hidden_states + fla_out
            self.cache = new_cache
        else:
            write_vecs = self.memory_writer(self.write_norm(hidden_states))
            write_vecs_rot = self.orthogonal_rotation(write_vecs)
            fla_out, new_cache = self._gdn_recurrent(write_vecs_rot, attention_mask=None)
            fla_out = self.orthogonal_rotation(fla_out, inverse=True)
            self.last_write_output = fla_out
            self.cache = new_cache
            if self.write_residual and self.read_mode in ('unpool', 'cross_attn'):
                hidden_states = hidden_states + self.memory_reader(
                    self.read_norm(hidden_states), self.last_write_output
                )

        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    # ───── parallel-prefill path ─────
    def _forward_parallel(self, hidden_states, *args, **kwargs):
        """Single-pass over S segments. Order: WRITE → GDN → READ → ATTN.

        WRITE is taken from pre-attn tokens (vs v5 which writes from post-attn).
        After this layer, READ at the *next* segment in the same layer is supplied
        via mem_shifted, which is what the recurrent code does (modulo phase
        shift). Cache + last_write_output are updated for the subsequent qt
        (recurrent) segment.
        """
        S, T, M = self._p_S, self._p_T, self._p_M
        B, L, d = hidden_states.shape
        assert L == S * T, f"parallel pass: got L={L}, expected S*T={S*T}"

        # ── WRITE (or identity full-token stream) ──
        if self.write_mode == 'identity':
            x = self.fla_norm(hidden_states)                       # (B, S*T, d)
            x_rot = self.orthogonal_rotation(x)
            fo = self.fla_layer(
                x_rot, attention_mask=None,
                past_key_values=self.cache, use_cache=True,
            )
            fla_out, new_cache = fo[0], fo[2]
            fla_out = self.orthogonal_rotation(fla_out, inverse=True)
            # Apply base_layer with block-diag causal mask
            # (no read in identity mode — symmetry forces read_mode='identity')
            kwargs2 = dict(kwargs)
            kwargs2['attention_mask'] = self._p_attn_mask
            output = self.base_layer(hidden_states + fla_out, *args, **kwargs2)
            hidden_states = output[0] if isinstance(output, tuple) else output
            self.cache = new_cache
            # Stash last memory: identity has no last_write_output (read is via GDN
            # readout in v5's gdn_readout mode, not used here)
            self.last_write_output = None
        else:
            write_vecs = self.memory_writer.parallel(
                self.write_norm(hidden_states), S, T, M
            )                                                       # (B, S*M, d_v)
            write_vecs_rot = self.orthogonal_rotation(write_vecs)
            fo = self.fla_layer(
                write_vecs_rot, attention_mask=None,
                past_key_values=self.cache, use_cache=True,
            )
            mem, new_cache = fo[0], fo[2]
            mem = self.orthogonal_rotation(mem, inverse=True)       # (B, S*M, d_v)
            self.cache = new_cache
            # last_write_output for the qt (recurrent) segment = final segment's mem block
            self.last_write_output = mem[:, -M:, :].contiguous()

            # ── READ: shift memory by one segment ──
            mem_shifted = torch.zeros_like(mem)
            if S > 1:
                mem_shifted[:, M:, :] = mem[:, :-M, :]
            # segment 0 reads from zeros → softmax(0)=uniform over M zeros = 0 contribution
            # for unpool (matmul with v of zeros = 0); cross_attn similar. OK.

            read_out = self.memory_reader.parallel(
                self.read_norm(hidden_states), mem_shifted, S, T, M
            ) if self.read_mode in ('unpool', 'cross_attn') else 0
            # Mask out segment 0's read contribution explicitly (zeros mem could be
            # non-zero via v_proj bias; we use bias=False but be safe)
            if isinstance(read_out, torch.Tensor):
                seg_mask = torch.ones(S, device=hidden_states.device, dtype=hidden_states.dtype)
                seg_mask[0] = 0.0
                read_out = read_out.view(B, S, T, d) * seg_mask.view(1, S, 1, 1)
                read_out = read_out.view(B, S * T, d)
                hidden_states = hidden_states + read_out

            # ── ATTN with block-diag causal mask ──
            kwargs2 = dict(kwargs)
            kwargs2['attention_mask'] = self._p_attn_mask
            output = self.base_layer(hidden_states, *args, **kwargs2)
            hidden_states = output[0] if isinstance(output, tuple) else output

            # ── optional write_residual: post-attn tokens enriched from this layer's mem ──
            if self.write_residual and self.read_mode in ('unpool', 'cross_attn'):
                # Use UN-shifted mem (each segment reads its own fresh block)
                hidden_states = hidden_states + self.memory_reader.parallel(
                    self.read_norm(hidden_states), mem, S, T, M
                )

        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    def reset_memory(self):
        self.cache = Cache()
        self.last_write_output = None


# ───────────────────────── config ───────────────────────────────────────────
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
        state_size=128,
        write_mode='cross_attn',
        read_mode='cross_attn',
        write_residual=False,
        use_orthogonal_rotation=False,
        num_memory_vectors=1,
        write_value_dim=None,
        num_memory_heads=1,
        num_write_vectors=None,
        num_read_heads=None,
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
        self.use_orthogonal_rotation = use_orthogonal_rotation
        self.num_memory_vectors = num_write_vectors if num_write_vectors is not None else num_memory_vectors
        self.write_value_dim = write_value_dim
        self.num_memory_heads = num_read_heads if num_read_heads is not None else num_memory_heads
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    @property
    def num_write_vectors(self): return self.num_memory_vectors
    @property
    def num_read_heads(self): return self.num_memory_heads

    def get(self, attr, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self):
        return {
            "num_heads": self.num_heads,
            "head_dim": self.head_dim,
            "expand": self.expand_v,
            "conv_kernel": self.conv_size,
            "state_size": self.state_size,
        }


# ───────────────────────── cell with parallel_forward ───────────────────────
def _build_block_diag_causal_mask(S, T, device, dtype):
    """(1, 1, S*T, S*T) additive mask: -inf except where same segment AND key<=query."""
    L = S * T
    idx = torch.arange(L, device=device)
    seg = idx // T
    valid = (seg.unsqueeze(0) == seg.unsqueeze(1)) & (idx.unsqueeze(1) >= idx.unsqueeze(0))
    # rows = query i, cols = key j. valid iff same segment and j <= i.
    mask = torch.zeros(L, L, device=device, dtype=dtype)
    mask.masked_fill_(~valid, float('-inf'))
    return mask.view(1, 1, L, L)


class RecurrentMemoryCell(nn.Module):
    @staticmethod
    def _get_transformer_layers(base_model):
        if hasattr(base_model, "model"):
            return base_model.model.layers
        elif hasattr(base_model, "transformer"):
            return base_model.transformer.h
        raise AttributeError(f"Cannot find transformer layers in {type(base_model).__name__}")

    def __init__(self, base_model, fla_layer_name="Mamba2", num_memory_vectors=1,
                 write_mode='cross_attn', read_mode='cross_attn', write_value_dim=None,
                 num_memory_heads=1, write_residual=False,
                 use_orthogonal_rotation=False, **fla_layer_kwargs):
        super().__init__()
        self.model = base_model
        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        gdn_hidden_size = model_hidden_size if write_mode == 'identity' else (write_value_dim or model_hidden_size)
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        layer_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(layer_cls.__init__)
        excluded = {"self", "hidden_size", "layer_idx"}
        filtered_kwargs = {k: v for k, v in fla_layer_kwargs.items()
                           if k in sig.parameters and k not in excluded}

        transformer_layers = self._get_transformer_layers(base_model)
        for i, layer in enumerate(transformer_layers):
            fla_layer = layer_cls(
                hidden_size=gdn_hidden_size, layer_idx=0, **filtered_kwargs,
            ).to(dtype=model_dtype, device=model_device)
            fla_layer = RecurrentLayerWithSkip(fla_layer)
            wrapped = RecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer, model_hidden_size=model_hidden_size,
                num_memory_vectors=num_memory_vectors, write_mode=write_mode,
                read_mode=read_mode, write_value_dim=write_value_dim,
                num_memory_heads=num_memory_heads, write_residual=write_residual,
                use_orthogonal_rotation=use_orthogonal_rotation,
            )
            transformer_layers[i] = wrapped

    def _set_parallel(self, on, S=0, T=0, M=0, attn_mask=None):
        for layer in self._get_transformer_layers(self.model):
            layer.parallel_mode = on
            layer._p_S, layer._p_T, layer._p_M = S, T, M
            layer._p_attn_mask = attn_mask

    def _get_block_diag_mask(self, S, T, device, dtype):
        key = (S, T, device.type, device.index if device.index is not None else -1, dtype)
        cache = getattr(self, "_mask_cache", None)
        if cache is None:
            cache = {}
            self._mask_cache = cache
        m = cache.get(key)
        if m is None:
            m = _build_block_diag_causal_mask(S, T, device, dtype)
            cache[key] = m
        return m

    def parallel_forward(self, input_ids, S, T, M, **kwargs):
        """Run the model in parallel-prefill mode over a concatenated (B, S*T) input."""
        device = input_ids.device
        model_dtype = next(self.model.parameters()).dtype
        attn_mask = self._get_block_diag_mask(S, T, device, model_dtype)
        self._set_parallel(True, S=S, T=T, M=M, attn_mask=attn_mask)
        try:
            out = self.model(input_ids=input_ids, attention_mask=attn_mask, **kwargs)
        finally:
            self._set_parallel(False)
        return out

    def forward(self, input_ids, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)

    def generate(self, input_ids, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


# ───────────────────────── wrapper: prefill + decode ────────────────────────
class RecurrentMemoryWrapperBase(nn.Module):
    """Splits the segment list into (context segments, qt segment).

    Context segments — all equal length T — go through parallel_forward as a
    single (B, S*T) pass. The final segment (qt) goes through the recurrent
    path on a single forward.
    """

    def __init__(self, memory_cell, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None,
                *args, **kwargs):
        cell_outputs = []

        # Split: context = all but last; qt = last
        context_segs = segments[:-1] if len(segments) > 1 else []
        qt_seg = segments[-1]

        if context_segs:
            # Verify uniform T across context segments
            T_list = [seg["input_ids"].shape[1] for seg in context_segs]
            assert len(set(T_list)) == 1, f"v5p requires uniform tokens_per_segment; got {T_list}"
            T = T_list[0]
            S = len(context_segs)
            cat_ids = torch.cat([seg["input_ids"] for seg in context_segs], dim=1)   # (B, S*T)
            # Determine M from any layer
            transformer_layers = RecurrentMemoryCell._get_transformer_layers(self.memory_cell.model)
            M = transformer_layers[0].num_memory_vectors

            ctx_out = self.memory_cell.parallel_forward(
                cat_ids, S=S, T=T, M=M, output_hidden_states=True,
            )
            cell_outputs.append(ctx_out)

        # qt segment via recurrent path (single forward pass)
        qt_out = self.memory_cell(
            input_ids=qt_seg["input_ids"],
            attention_mask=qt_seg["attention_mask"],
            output_hidden_states=True,
        )
        cell_outputs.append(qt_out)

        labels_mask = None
        if "labels_mask" in segments[0]:
            labels_mask = torch.cat([seg["labels_mask"] for seg in segments], dim=1)

        return self.process_outputs(
            cell_outputs, labels=labels, labels_mask=labels_mask,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states, **kwargs,
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
            flat_logits = shift_logits.view(-1, shift_logits.size(-1))
            flat_labels = shift_labels.view(-1)
            labels_mask = kwargs.get("labels_mask")
            if labels_mask is not None:
                shift_mask = labels_mask[..., :-1].contiguous().view(-1)
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


# ───────────────────────── top-level model ──────────────────────────────────
class RecurrentMemoryBase(PreTrainedModel):
    config_class = RecurrentMemoryConfig

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM
        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(config.from_pretrained)
        else:
            base_config = (config.base_model_config if config.base_model_config is not None
                           else AutoConfig.from_pretrained(config.base_model_name))
            base_model = AutoModelForCausalLM.from_config(base_config)
        self.rmm_config = config
        memory_cell = RecurrentMemoryCell(
            base_model, fla_layer_name=config.fla_layer_name,
            num_memory_vectors=config.num_memory_vectors,
            write_mode=config.write_mode, read_mode=config.read_mode,
            write_value_dim=config.write_value_dim,
            num_memory_heads=config.num_memory_heads,
            write_residual=config.write_residual,
            use_orthogonal_rotation=config.use_orthogonal_rotation,
            **config.fla_layer_kwargs(),
        )
        self.rmt = RecurrentMemoryWrapperBase(
            memory_cell, max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id, answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id, eos_token_id=config.eos_token_id,
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
            wp = cached_file(pretrained_model_name_or_path, "model.safetensors", **kwargs)
            from safetensors.torch import load_file
            state_dict = load_file(wp, device="cpu")
        except (OSError, HfHubHTTPError):
            try:
                wp = cached_file(pretrained_model_name_or_path, "pytorch_model.bin", **kwargs)
                state_dict = torch.load(wp, map_location="cpu")
            except (OSError, HfHubHTTPError):
                print(f"Warning: no weights found for {pretrained_model_name_or_path}. Randomly initialised.")
        if state_dict is not None:
            model.load_state_dict(state_dict, strict=False)
        return model
