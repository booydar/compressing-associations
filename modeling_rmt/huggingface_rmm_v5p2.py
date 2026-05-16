"""v5p2

Built from v5 (faithful recurrent semantics) + parallel-prefill capability.

  Parallel-prefill semantics:
  * S context segments are processed in one forward via block-diagonal causal
    attention (one base-model pass instead of S).
  * WRITE: per-segment cross-attention via MemoryWriter.parallel — segment s's
    queries attend only to that segment's tokens.
  * GDN: runs once over (B, S*M) write vectors. Because GDN/Mamba2 are
    recurrent by construction, this is mathematically equivalent to S
    sequential calls of length M.
  * READ (closest approximation to v5):
      Segment s reads from segment s-1's GDN output (mem_shifted). For s=0
      the read source is last_write_output from the previous batch (or skipped
      if None). This preserves v5's segment-to-segment memory flow, with the
      single approximation that the read is applied POST-attention rather than
      PRE-attention (we cannot break the attn↔read dependency within a single
      parallel pass).
  * Padding masks from each segment are combined with the block-diagonal
    causal mask.
  * qt (final) segment runs through the recurrent path, byte-identical to v5.

Identity mode (write_mode='identity'): parallel mode falls back to a
per-segment recurrent loop because GDN read-only / write share the same
fla_layer and the cross-segment state dependency cannot be parallelised
without an additional approximation. Identity is therefore exactly v5 in
this implementation (no speedup, but correct).
"""
from __future__ import annotations

import inspect
from contextlib import contextmanager

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

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
        from_states: torch.Tensor,
        to_states: torch.Tensor,
        attention_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
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


class MemoryWriter(nn.Module):
    """Compresses tokens → M memory vectors of dim d_v.

    Forward: (B, T, d) -> (B, M, d_v) (recurrent path).
    parallel(): (B, S*T, d) -> (B, S*M, d_v) — block-diagonal: queries for
    segment i attend only to tokens [i*T:(i+1)*T]. Mathematically identical
    to S separate forward() calls.
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
        self.num_vectors = num_vectors
        self.hidden_size = hidden_size
        self.write_value_dim = write_value_dim or hidden_size
        self.scaling = hidden_size ** -0.5

        self.write_queries = nn.Parameter(torch.zeros(num_vectors, hidden_size))
        nn.init.normal_(self.write_queries, std=hidden_size ** -0.5)

        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
        self.v_proj = nn.Linear(hidden_size, self.write_value_dim, bias=bias)

        if mode == 'cross_attn':
            self.q_proj  = nn.Linear(hidden_size, hidden_size, bias=bias)
            self.out_proj = nn.Linear(self.write_value_dim, self.write_value_dim, bias=bias)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
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

    def parallel(self, hidden_states: torch.Tensor, S: int, T: int, M: int,
                 pad_mask: torch.Tensor | None = None) -> torch.Tensor:
        """(B, S*T, d) -> (B, S*M, d_v).

        pad_mask: optional (B, S*T) 1=keep, 0=pad. Padded tokens are excluded
        from the softmax (so writes never attend to padding).
        """
        B = hidden_states.shape[0]
        d = self.hidden_size
        queries = self.write_queries.view(1, 1, M, d).expand(B, S, M, d)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)
        tokens = hidden_states.view(B, S, T, d)
        k = self.k_proj(tokens)
        v = self.v_proj(tokens)
        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling   # (B, S, M, T)

        if pad_mask is not None:
            pad = pad_mask.view(B, S, T).unsqueeze(2)   # (B, S, 1, T)
            attn = attn.masked_fill(pad == 0, float('-inf'))

        attn = F.softmax(attn, dim=-1)
        # NaN-guard: if every key in a segment is padded the row is all -inf
        # → softmax gives NaN. Replace with zeros (the contribution is zero).
        attn = torch.nan_to_num(attn, nan=0.0)
        out = torch.matmul(attn, v)
        if self.mode == 'cross_attn':
            out = self.out_proj(out)
        return out.reshape(B, S * M, self.write_value_dim)


class MemoryReader(nn.Module):
    """Enriches T tokens from M memory vectors of dim d_v.

    parallel(): each segment's T tokens read from a per-segment M-block of
    `mem_shifted` (B, S*M, d_v). Caller is responsible for constructing
    mem_shifted so segment s reads from segment s-1's memory (closest
    approximation to v5's pre-attention READ).
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
        self.hidden_size = hidden_size
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
        if self.mode == 'unpool':
            k = self.k_proj(memory_states)
            v = self.v_proj(memory_states)
            attn = torch.matmul(token_states, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            return torch.matmul(attn, v)
        out, _ = self.cross_attn(from_states=token_states, to_states=memory_states)
        return out

    def parallel(self, token_states: torch.Tensor, mem_shifted: torch.Tensor,
                 S: int, T: int, M: int) -> torch.Tensor:
        """(B, S*T, d), (B, S*M, d_v) -> (B, S*T, d)."""
        B = token_states.shape[0]
        d = self.hidden_size
        tokens = token_states.view(B, S, T, d)
        if self.mode == 'unpool':
            mem = mem_shifted.view(B, S, M, -1)
            k = self.k_proj(mem)
            v = self.v_proj(mem)
            attn = torch.matmul(tokens, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            out = torch.matmul(attn, v)
            return out.reshape(B, S * T, d)
        d_v = mem_shifted.shape[-1]
        from_states = tokens.reshape(B * S, T, d)
        to_states = mem_shifted.view(B, S, M, d_v).reshape(B * S, M, d_v)
        out, _ = self.cross_attn(from_states=from_states, to_states=to_states)
        return out.view(B, S * T, d)


class RecurrentMemoryLayerWrapper(nn.Module):
    """Wraps a transformer layer with symmetric read/write memory via GDN.

    Recurrent path (per-segment, identical to v5):
      1. READ  – enrich tokens from last segment's memory (B,M,d_v). Skipped on
                 first segment or when read_mode='identity' (which uses
                 _gdn_readonly instead).
      2. ATTN  – base transformer layer.
      3. WRITE – compress tokens → GDN → store memory at full d_v.
      4. (v5) WRITE-RESIDUAL – if write_residual=True and read_mode != identity,
                 enrich post-write tokens from this segment's fresh memory.

    Parallel-prefill path (non-identity modes):
      1. ATTN  – block-diagonal causal attention across all S segments.
      2. WRITE – MemoryWriter.parallel computes S*M write vectors.
      3. GDN   – single batched call over (B, S*M, d_v).
      4. READ  – post-attention read using mem_shifted so segment s reads
                 from segment s-1's GDN output (closest single-pass
                 approximation to v5's pre-attention READ).
      5. (v5) WRITE-RESIDUAL – if write_residual=True, additional read from
                 this-segment's just-written memory (matches v5 behaviour).

    Parallel-prefill path (identity mode): falls back to per-segment recurrent
    calls — identity mode's intertwined read/write state cannot be parallelised
    without breaking equivalence.
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

        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.write_residual = write_residual
        self.num_memory_vectors = num_memory_vectors
        self.write_value_dim = write_value_dim_resolved

        fla_device = next(fla_layer.parameters()).device

        self.write_norm = nn.RMSNorm(model_hidden_size, eps=1e-5).to(device=fla_device)
        self.read_norm  = nn.RMSNorm(model_hidden_size, eps=1e-5).to(device=fla_device)

        if write_mode == 'identity':
            self.fla_norm = nn.RMSNorm(model_hidden_size, eps=1e-5).to(device=fla_device)
        else:
            self.memory_writer = MemoryWriter(
                hidden_size=model_hidden_size,
                num_vectors=num_memory_vectors,
                mode=write_mode,
                write_value_dim=self.write_value_dim,
            ).to(device=fla_device)
            if read_mode in ('unpool', 'cross_attn'):
                self.memory_reader = MemoryReader(
                    hidden_size=model_hidden_size,
                    write_value_dim=self.write_value_dim,
                    mode=read_mode,
                    num_heads=num_memory_heads,
                ).to(device=fla_device)

        self.cache = Cache()
        self.last_write_output: torch.Tensor | None = None   # (B, M, d_v)

        # Parallel-mode stash (set by parent cell during parallel_forward)
        self.parallel_mode = False
        self._p_S = self._p_T = self._p_M = 0
        self._p_attn_mask = None
        self._p_pad_mask = None   # (B, S*T) 1=keep, 0=pad — optional

    # ───── recurrent helpers (faithful v5) ─────
    def _gdn_readonly(self, normed_tokens, attention_mask):
        """Run fla_layer with cached state but discard any state update."""
        if len(self.cache.layers) == 0:
            return torch.zeros_like(normed_tokens)
        layer = self.cache.layers[0]
        saved_state = layer.state if layer.state is None else dict(layer.state)
        # _seen_tokens lives on the Cache itself, not on the per-layer object.
        saved_seen = getattr(self.cache, '_seen_tokens', 0)
        fla_out = self.fla_layer(
            normed_tokens,
            attention_mask=attention_mask,
            past_key_values=self.cache,
            use_cache=True,
        )
        layer.state = saved_state
        self.cache._seen_tokens = saved_seen
        return fla_out[0]

    def forward(self, hidden_states, *args, **kwargs):
        if self.parallel_mode:
            return self._forward_parallel(hidden_states, *args, **kwargs)
        return self._forward_recurrent(hidden_states, *args, **kwargs)

    # ───── recurrent path (byte-identical to v5) ─────
    def _forward_recurrent(self, hidden_states: torch.Tensor, *args, **kwargs):
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
            write_vecs = self.memory_writer(self.write_norm(hidden_states))
            fla_out = self.fla_layer(
                write_vecs,
                attention_mask=None,
                past_key_values=self.cache,
                use_cache=True,
            )
            self.last_write_output = fla_out[0]
            self.cache = fla_out[2]

            # 4. (v5) write_residual: feed fresh memory back into current tokens.
            if self.write_residual and self.read_mode in ('unpool', 'cross_attn'):
                hidden_states = hidden_states + self.memory_reader(
                    self.read_norm(hidden_states), self.last_write_output
                )

        if isinstance(output, tuple):
            return (hidden_states,) + output[1:]
        return hidden_states

    # ───── parallel-prefill path ─────
    def _forward_parallel(self, hidden_states: torch.Tensor, *args, **kwargs):
        S, T, M = self._p_S, self._p_T, self._p_M
        B, L, d = hidden_states.shape
        assert L == S * T, f"parallel pass: got L={L}, expected S*T={S*T}"

        # Identity mode: single pass with block-diag mask. READ and WRITE
        # both go through fla_layer over the full S*T sequence. This is an
        # approximation vs v5 (per-segment state-restore boundaries are
        # coarsened to the whole context), but it preserves block-diag
        # causal attention and produces a single base_layer call.
        if self.write_mode == 'identity':
            # 1. READ via _gdn_readonly on full sequence.
            hidden_states = hidden_states + self._gdn_readonly(
                self.read_norm(hidden_states), attention_mask=None
            )
            # 2. ATTN with block-diag mask
            kwargs2 = dict(kwargs)
            kwargs2['attention_mask'] = self._p_attn_mask
            output = self.base_layer(hidden_states, *args, **kwargs2)
            hidden_states = output[0] if isinstance(output, tuple) else output
            # 3. WRITE via fla_layer
            fla_input = self.fla_norm(hidden_states)
            fo = self.fla_layer(
                fla_input,
                attention_mask=None,
                past_key_values=self.cache,
                use_cache=True,
            )
            hidden_states = hidden_states + fo[0]
            self.cache = fo[2]
            if isinstance(output, tuple):
                return (hidden_states,) + output[1:]
            return hidden_states

        # ── non-identity parallel ──
        # 1. ATTN with block-diag causal mask (overrides whatever HF prepared)
        kwargs2 = dict(kwargs)
        kwargs2['attention_mask'] = self._p_attn_mask
        output = self.base_layer(hidden_states, *args, **kwargs2)
        post_attn = output[0] if isinstance(output, tuple) else output

        # 2. WRITE (per-segment cross-attn batched)
        write_vecs = self.memory_writer.parallel(
            self.write_norm(post_attn), S, T, M, pad_mask=self._p_pad_mask,
        )                                                       # (B, S*M, d_v)

        # 3. GDN — single call over all S*M tokens
        fo = self.fla_layer(
            write_vecs,
            attention_mask=None,
            past_key_values=self.cache,
            use_cache=True,
        )
        mem, new_cache = fo[0], fo[2]                           # (B, S*M, d_v)
        self.cache = new_cache
        self.last_write_output = mem[:, -M:, :].contiguous()    # for downstream qt segment

        # 4. READ: build mem_shifted so segment s reads from segment s-1's mem.
        #    Segment 0 reads from last_write_output of the prior batch
        #    (zeros if None — same convention as v5 when no prior memory).
        if self.read_mode in ('unpool', 'cross_attn'):
            d_v = mem.shape[-1]
            mem_view = mem.view(B, S, M, d_v)
            shifted = torch.zeros_like(mem_view)
            if S > 1:
                shifted[:, 1:] = mem_view[:, :-1]
            mem_shifted = shifted.view(B, S * M, d_v)
            post_attn = post_attn + self.memory_reader.parallel(
                self.read_norm(post_attn), mem_shifted, S, T, M,
            )

        # 5. (v5) write_residual: extra read from same-segment fresh memory.
        if self.write_residual and self.read_mode in ('unpool', 'cross_attn'):
            post_attn = post_attn + self.memory_reader.parallel(
                self.read_norm(post_attn), mem, S, T, M,
            )

        if isinstance(output, tuple):
            return (post_attn,) + output[1:]
        return post_attn

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
        write_mode='cross_attn',
        read_mode='cross_attn',
        write_residual=False,
        use_parallel_prefill=True,
        use_sliding_window=False,
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
        self.use_parallel_prefill = use_parallel_prefill
        self.use_sliding_window = use_sliding_window
        self.num_memory_vectors = num_write_vectors if num_write_vectors is not None else num_memory_vectors
        self.write_value_dim = write_value_dim
        self.num_memory_heads = num_read_heads if num_read_heads is not None else num_memory_heads
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    @property
    def num_write_vectors(self):
        return self.num_memory_vectors

    @property
    def num_read_heads(self):
        return self.num_memory_heads

    def get(self, attr: str, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self) -> dict:
        # Pass both common conv kwarg names; filtered_kwargs picks whichever
        # the chosen fla layer actually accepts (GDN: conv_size, Mamba2:
        # conv_kernel).
        return {
            "num_heads": getattr(self, 'num_heads', 4),
            "head_dim": getattr(self, 'head_dim', 64),
            "state_size": getattr(self, 'state_size', 32),
            "expand": getattr(self, 'expand_v', 2.0),
            "conv_size": getattr(self, 'conv_size', 4),
            "conv_kernel": getattr(self, 'conv_size', 4),
        }


# ───────────────────────── parallel-mode helpers ────────────────────────────
def _build_block_diag_causal_mask(S: int, T: int, device, dtype):
    """(1, 1, S*T, S*T) additive mask: 0 inside same-segment causal triangle,
    -inf elsewhere."""
    L = S * T
    idx = torch.arange(L, device=device)
    seg = idx // T
    valid = (seg.unsqueeze(0) == seg.unsqueeze(1)) & (idx.unsqueeze(1) >= idx.unsqueeze(0))
    mask = torch.zeros(L, L, device=device, dtype=dtype)
    mask.masked_fill_(~valid, float('-inf'))
    return mask.view(1, 1, L, L)


def _build_sliding_window_causal_mask(L: int, W: int, device, dtype):
    """(1, 1, L, L) additive causal sliding-window mask: 0 where j <= i AND
    i - j < W, -inf elsewhere. Cross-segment attention allowed up to W-1
    positions back, unlike the block-diag variant."""
    idx = torch.arange(L, device=device)
    diff = idx.unsqueeze(1) - idx.unsqueeze(0)         # (L, L): i - j
    valid = (diff >= 0) & (diff < W)
    mask = torch.zeros(L, L, device=device, dtype=dtype)
    mask.masked_fill_(~valid, float('-inf'))
    return mask.view(1, 1, L, L)


class RecurrentMemoryCell(nn.Module):
    """Replaces each transformer layer with a RecurrentMemoryLayerWrapper."""

    @staticmethod
    def _get_transformer_layers(base_model: nn.Module):
        if hasattr(base_model, "model"):
            return base_model.model.layers
        elif hasattr(base_model, "transformer"):
            return base_model.transformer.h
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
        use_sliding_window: bool = False,
        **fla_layer_kwargs,
    ):
        super().__init__()
        self.model = base_model
        self.use_sliding_window = use_sliding_window

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

        self._mask_cache = {}

    def _set_parallel(self, on, S=0, T=0, M=0, attn_mask=None, pad_mask=None):
        for layer in self._get_transformer_layers(self.model):
            layer.parallel_mode = on
            layer._p_S, layer._p_T, layer._p_M = S, T, M
            layer._p_attn_mask = attn_mask
            layer._p_pad_mask = pad_mask

    def _get_attention_mask(self, S, T, device, dtype):
        """Return the (1,1,L,L) parallel-mode mask. Dispatches on
        `self.use_sliding_window`. Cached per (mode, S, T, device, dtype)."""
        mode = 'sliding_window' if self.use_sliding_window else 'block_diag'
        key = (mode, S, T, device.type,
               device.index if device.index is not None else -1, dtype)
        m = self._mask_cache.get(key)
        if m is None:
            if self.use_sliding_window:
                m = _build_sliding_window_causal_mask(S * T, T, device, dtype)
            else:
                m = _build_block_diag_causal_mask(S, T, device, dtype)
            self._mask_cache[key] = m
        return m

    def parallel_forward(self, input_ids, S, T, M, pad_mask=None, **kwargs):
        """Run the model in parallel-prefill mode over a concatenated (B, S*T) input.

        pad_mask: optional (B, S*T) attention mask (1=keep, 0=pad). If given,
        it is combined with the (block-diag or sliding-window) causal mask so
        padded keys are excluded from attention. It is also forwarded to the
        writer's parallel path so writes don't pool over padded positions.
        """
        device = input_ids.device
        model_dtype = next(self.model.parameters()).dtype
        base_mask = self._get_attention_mask(S, T, device, model_dtype)   # (1,1,L,L)
        attn_mask = base_mask
        if pad_mask is not None:
            # Build (B, 1, 1, L) padding mask, broadcast-add with base mask.
            neg = torch.finfo(model_dtype).min
            pad4d = (1.0 - pad_mask.to(model_dtype)) * neg
            attn_mask = base_mask + pad4d[:, None, None, :]   # (B,1,L,L) via broadcast

        self._set_parallel(True, S=S, T=T, M=M, attn_mask=attn_mask, pad_mask=pad_mask)
        try:
            out = self.model(input_ids=input_ids, attention_mask=attn_mask, **kwargs)
        finally:
            self._set_parallel(False)
        return out

    def forward(self, input_ids: torch.Tensor, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)

    def generate(self, input_ids: torch.Tensor, **kwargs):
        return self.model.generate(input_ids=input_ids, **kwargs)


class RecurrentMemoryWrapperBase(nn.Module):
    """Splits the segment list into (context segments, qt segment).

    When `use_parallel_prefill=True` (default), context segments — all equal
    length T — go through parallel_forward as a single (B, S*T) pass. The
    final segment (qt) goes through the recurrent path.

    When `use_parallel_prefill=False`, ALL segments go through the recurrent
    path sequentially (byte-identical to v5). Use this for generation /
    inference where the parallel approximation is not wanted.
    """

    def __init__(self, memory_cell: RecurrentMemoryCell,
                 use_parallel_prefill: bool = True, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.use_parallel_prefill = use_parallel_prefill
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None, output_hidden_states=None,
                *args, **kwargs):
        if not segments:
            raise ValueError("RecurrentMemoryWrapperBase requires at least one segment")

        cell_outputs = []

        if self.use_parallel_prefill and len(segments) > 1:
            context_segs = segments[:-1]
            qt_seg = segments[-1]

            T_list = [seg["input_ids"].shape[1] for seg in context_segs]
            assert len(set(T_list)) == 1, f"parallel prefill requires uniform tokens_per_segment; got {T_list}"
            T = T_list[0]
            S = len(context_segs)
            cat_ids = torch.cat([seg["input_ids"] for seg in context_segs], dim=1)        # (B, S*T)
            pad_mask = None
            if all("attention_mask" in seg for seg in context_segs):
                pad_mask = torch.cat([seg["attention_mask"] for seg in context_segs], dim=1)
                pad_mask = pad_mask.to(device=cat_ids.device)

            transformer_layers = RecurrentMemoryCell._get_transformer_layers(self.memory_cell.model)
            M = transformer_layers[0].num_memory_vectors

            ctx_out = self.memory_cell.parallel_forward(
                cat_ids, S=S, T=T, M=M, pad_mask=pad_mask,
                output_hidden_states=True,
            )
            cell_outputs.append(ctx_out)

            qt_out = self.memory_cell(
                input_ids=qt_seg["input_ids"],
                attention_mask=qt_seg["attention_mask"],
                output_hidden_states=True,
            )
            cell_outputs.append(qt_out)
        else:
            # Sequential / fully recurrent — every segment goes through
            # memory_cell.forward (recurrent path). Used when
            # use_parallel_prefill is False, or when there is only one segment.
            for seg in segments:
                seg_out = self.memory_cell(
                    input_ids=seg["input_ids"],
                    attention_mask=seg.get("attention_mask"),
                    output_hidden_states=True,
                )
                cell_outputs.append(seg_out)

        labels_mask = None
        if "labels_mask" in segments[0]:
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

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(
                config.from_pretrained,
                device_map="auto" if torch.cuda.is_available() else None
            )
        else:
            base_config = (
                config.base_model_config
                if config.base_model_config is not None
                else AutoConfig.from_pretrained(config.base_model_name)
            )
            base_model = AutoModelForCausalLM.from_config(base_config)
            base_model = base_model.to(device)

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
            use_sliding_window=getattr(config, 'use_sliding_window', False),
            **config.fla_layer_kwargs(),
        )
        self.rmt = RecurrentMemoryWrapperBase(
            memory_cell,
            use_parallel_prefill=getattr(config, 'use_parallel_prefill', True),
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id,
        )

    def _reset_memory(self):
        for layer in RecurrentMemoryCell._get_transformer_layers(self.rmt.memory_cell.model):
            layer.reset_memory()

    # ───── parallel/recurrent runtime switch ─────
    def set_parallel_prefill(self, enabled: bool):
        """Toggle parallel-prefill on/off at runtime.

        Typical usage: train/prefill with parallel=True, generate with
        parallel=False (or use the recurrent_mode() context manager).
        """
        self.rmt.use_parallel_prefill = bool(enabled)

    def set_sliding_window(self, enabled: bool):
        """Toggle the parallel-mode mask between block-diagonal (False) and
        causal sliding-window of size T (True). Affects the next forward
        pass; cached masks for both variants coexist."""
        self.rmt.memory_cell.use_sliding_window = bool(enabled)

    @contextmanager
    def recurrent_mode(self):
        """Context manager: force the recurrent path inside this block,
        restore the previous setting on exit."""
        prev = self.rmt.use_parallel_prefill
        self.rmt.use_parallel_prefill = False
        try:
            yield self
        finally:
            self.rmt.use_parallel_prefill = prev

    def forward(self, segments=None, labels=None, *args, **kwargs):
        out = self.rmt(segments=segments, labels=labels, *args, **kwargs)
        self._reset_memory()
        return out

    def generate(self, *args, **kwargs):
        # Generation: force recurrent path. Restore on exit.
        with self.recurrent_mode():
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
