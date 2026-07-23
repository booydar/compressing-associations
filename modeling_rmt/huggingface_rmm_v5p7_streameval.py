"""v5p7-streameval: byte-for-byte copy of huggingface_rmm_v5p7 plus one opt-in
memory-frugal eval path (config.eval_stream_logits, default False -> behavior
identical to v5p7, so the v5p7 equivalence tests still hold).

When eval_stream_logits=True AND the module is in eval mode AND running the
recurrent path, forward() streams: each segment's logits are argmaxed to int
predictions immediately (the float logits are freed on the next iteration) and
only the FINAL segment's float logits are retained, for the loss. This avoids
ever materializing the (B, S*T, vocab) float tensor that OOMs the base v5p7 at
>=1024 segments. Correctness rests on answer labels living solely in the final
segment (true for babilong collate; asserted at runtime). See _forward_stream.
The returned `logits` are (B, S*T) int predictions, so the runner's
preprocess_logits_for_metrics must pass 2-D logits through unchanged.

v5p7: v5p4 with the per-layer double-residual bug removed.

v5p4 wrapped the GDN with ``RecurrentLayerWithSkip`` (added an input→output
skip inside the wrapper) AND added another residual at the call site
(``out_h = post_attn + mem``). Composing both gave, in identity mode,

    out_h = post_attn + fla_norm(post_attn) + GDN(fla_norm(post_attn))

— a normalized copy of ``post_attn`` was being added back to ``post_attn``
itself every layer, every token. v5p7 keeps the call-site residual and
drops the wrapper, leaving exactly one skip per layer.

Resolved per-layer formulas (B = base Llama decoder layer, LN_f = fla_norm,
LN_r = read_norm, GDN with NO outer skip):

  identity (write_mode = read_mode = 'identity'):
      post_attn = B(x)
      mem       = GDN( LN_f(post_attn) )           # GDN cache persists across segments
      out_h     = post_attn + mem

  pool / unpool (or cross_attn) with shifted READ:
      post_attn = B(x)
      m_vecs    = compress(post_attn)              # (B, M, d_v)
      mem       = GDN( LN_f(m_vecs) )
      r         = decompress( LN_r(post_attn), prev_mem or 0 )
      prev_mem <- mem
      out_h     = post_attn + r

Parallel-prefill path is bit-equivalent to S sequential recurrent calls.
GDN cache (self.cache) and self.prev_mem are reset in reset_memory().

INVARIANT (enforced by tests/test_rmm_v5p7_single_skip.py):
  exactly ONE additive skip per layer at the call site, no wrapper-side skip.
  ``RecurrentLayerWithSkip`` is intentionally removed — do not reintroduce.
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


class LlamaCrossAttention(nn.Module):
    """Plain cross-attention. No causal mask, no RoPE."""

    def __init__(self, hidden_size, num_heads, kv_hidden_size=None,
                 head_dim=None, bias=False, out_hidden_size=None):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = head_dim if head_dim is not None else hidden_size // num_heads
        self.scaling = self.head_dim ** -0.5
        kv_hidden_size = kv_hidden_size or hidden_size

        self.q_proj = nn.Linear(hidden_size, num_heads * self.head_dim, bias=bias)
        self.k_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.v_proj = nn.Linear(kv_hidden_size, num_heads * self.head_dim, bias=bias)
        self.o_proj = nn.Linear(num_heads * self.head_dim,
                                out_hidden_size or hidden_size, bias=bias)

    def forward(self, from_states, to_states):
        B, Q, _ = from_states.shape
        K = to_states.shape[1]
        q = self.q_proj(from_states).view(B, Q, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(to_states).view(B, K, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(to_states).view(B, K, self.num_heads, self.head_dim).transpose(1, 2)
        w = torch.matmul(q, k.transpose(-2, -1)) * self.scaling
        w = F.softmax(w, dim=-1, dtype=torch.float32).to(q.dtype)
        out = torch.matmul(w, v).transpose(1, 2).reshape(B, Q, -1).contiguous()
        return self.o_proj(out)


class MemoryCompress(nn.Module):
    """T tokens per segment -> M memory vectors per segment.

    forward(h):              (B, T, d) -> (B, M, d_v)
    parallel(h, S, T, M):    (B, S*T, d) -> (B, S*M, d_v)

    The parallel call is block-diagonal: segment i's M queries attend only
    to tokens [i*T:(i+1)*T]. Bit-equivalent to S sequential forward() calls.
    """

    def __init__(self, hidden_size, num_vectors, mode='cross_attn',
                 write_value_dim=None, bias=False):
        super().__init__()
        if mode not in ('pool', 'cross_attn'):
            raise ValueError(f"mode must be 'pool' or 'cross_attn', got '{mode}'")
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

    def _attend(self, queries, tokens):
        k = self.k_proj(tokens)
        v = self.v_proj(tokens)
        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)
        if self.mode == 'cross_attn':
            out = self.out_proj(out)
        return out

    def forward(self, hidden_states):
        B = hidden_states.shape[0]
        queries = self.write_queries.unsqueeze(0).expand(B, -1, -1)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)
        return self._attend(queries, hidden_states)

    def parallel(self, hidden_states, S, T, M):
        B = hidden_states.shape[0]
        d = self.hidden_size
        queries = self.write_queries.view(1, 1, M, d).expand(B, S, M, d)
        if self.mode == 'cross_attn':
            queries = self.q_proj(queries)
        tokens = hidden_states.view(B, S, T, d)
        k = self.k_proj(tokens)
        v = self.v_proj(tokens)
        attn = torch.matmul(queries, k.transpose(-1, -2)) * self.scaling
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)
        if self.mode == 'cross_attn':
            out = self.out_proj(out)
        return out.reshape(B, S * M, self.write_value_dim)


class MemoryDecompress(nn.Module):
    """M memory vectors per segment -> T tokens per segment (residual content).

    forward(tokens, mem):              (B, T, d), (B, M, d_v) -> (B, T, d)
    parallel(tokens, mem, S, T, M):    (B, S*T, d), (B, S*M, d_v) -> (B, S*T, d)

    Same-segment read: tokens in segment s attend only to mem block s.
    Bit-equivalent between parallel and sequential.
    """

    def __init__(self, hidden_size, write_value_dim, mode='cross_attn',
                 num_heads=1, bias=False):
        super().__init__()
        if mode not in ('unpool', 'cross_attn'):
            raise ValueError(f"mode must be 'unpool' or 'cross_attn', got '{mode}'")
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
        if self.mode == 'unpool':
            k = self.k_proj(memory_states)
            v = self.v_proj(memory_states)
            attn = torch.matmul(token_states, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            return torch.matmul(attn, v)
        return self.cross_attn(from_states=token_states, to_states=memory_states)

    def parallel(self, token_states, mem, S, T, M):
        B = token_states.shape[0]
        d = self.hidden_size
        if self.mode == 'unpool':
            tokens = token_states.view(B, S, T, d)
            mem_v = mem.view(B, S, M, -1)
            k = self.k_proj(mem_v)
            v = self.v_proj(mem_v)
            attn = torch.matmul(tokens, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            out = torch.matmul(attn, v)
            return out.reshape(B, S * T, d)
        d_v = mem.shape[-1]
        from_states = token_states.view(B, S, T, d).reshape(B * S, T, d)
        to_states = mem.view(B, S, M, d_v).reshape(B * S, M, d_v)
        out = self.cross_attn(from_states=from_states, to_states=to_states)
        return out.view(B, S * T, d)


class RecurrentMemoryLayerWrapper(nn.Module):
    """Per-layer wrapper. Resolved formulas (single skip, see module docstring):

      identity:  out_h = post_attn + GDN(LN_f(post_attn))
      pool/xattn: out_h = post_attn + decompress(LN_r(post_attn), prev_mem)
                  where prev_mem is the previous segment's GDN(LN_f(compress(post_attn))).

    Exactly one additive skip at the call site. ``fla_layer`` here is a raw
    GDN/Mamba layer with NO outer WithSkip wrapper.
    """

    def __init__(self, base_layer, fla_layer, model_hidden_size,
                 num_memory_vectors=1, write_mode='cross_attn',
                 read_mode='cross_attn', write_value_dim=None,
                 num_memory_heads=1):
        super().__init__()
        identity = (write_mode == 'identity')
        if identity != (read_mode == 'identity'):
            raise ValueError("identity must be paired: write_mode and read_mode both 'identity'")
        wvd = write_value_dim if write_value_dim is not None else model_hidden_size
        if identity and wvd != model_hidden_size:
            raise ValueError("identity mode requires write_value_dim == model_hidden_size")
        if identity and num_memory_vectors not in (None, 0):
            # In identity mode, M == T is implicit (no compression).
            pass

        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.num_memory_vectors = num_memory_vectors
        self.write_value_dim = wvd

        self.fla_norm = nn.RMSNorm(wvd, eps=1e-5)
        self.read_norm = nn.RMSNorm(model_hidden_size, eps=1e-5)

        if identity:
            self.compress = None
            self.decompress = None
        else:
            self.compress = MemoryCompress(
                hidden_size=model_hidden_size,
                num_vectors=num_memory_vectors,
                mode=write_mode,
                write_value_dim=wvd,
            )
            self.decompress = MemoryDecompress(
                hidden_size=model_hidden_size,
                write_value_dim=wvd,
                mode=read_mode,
                num_heads=num_memory_heads,
            )

        self.cache = Cache()
        self.prev_mem = None  # last segment's mem block, (B, M, d_v); None on first segment
        self.parallel_mode = False
        self._p_S = self._p_T = self._p_M = 0
        self._p_attn_mask = None

        # Cache base_layer.forward positional-arg names so we can route *args
        # (e.g. GPT2's positional past_kv / cache_pos / attention_mask) to
        # the right keyword and override attention_mask without duplicates.
        try:
            sig = inspect.signature(self.base_layer.forward)
            self._base_param_names = [
                p for p in sig.parameters.keys() if p != 'self'
            ]
        except (TypeError, ValueError):
            self._base_param_names = ['hidden_states']

    def _call_base_layer(self, hidden_states, args, kwargs, attn_override=None):
        """Call self.base_layer with (hidden_states, *args, **kwargs), but
        optionally override the attention_mask kwarg. *args are mapped to
        keywords based on the cached signature so models that pass args
        positionally (GPT2) don't clash with an attention_mask kwarg."""
        names = self._base_param_names
        # names[0] is 'hidden_states' (already extracted). Map remaining
        # positional args to keyword names in order.
        pos_kwargs = dict(zip(names[1:1 + len(args)], args))
        merged = {**pos_kwargs, **kwargs}
        if attn_override is not None:
            merged['attention_mask'] = attn_override
        return self.base_layer(hidden_states, **merged)

    def reset_memory(self):
        self.cache = Cache()
        self.prev_mem = None

    def _gdn(self, x_norm):
        out = self.fla_layer(
            x_norm,
            attention_mask=None,
            past_key_values=self.cache,
            use_cache=True,
        )
        self.cache = out[2]
        return out[0]

    def forward(self, hidden_states, *args, **kwargs):
        if self.parallel_mode:
            return self._forward_parallel(hidden_states, *args, **kwargs)
        return self._forward_recurrent(hidden_states, *args, **kwargs)

    def _forward_recurrent(self, hidden_states, *args, **kwargs):
        output = self._call_base_layer(hidden_states, args, kwargs)
        post_attn = output[0] if isinstance(output, tuple) else output

        if self.write_mode == 'identity':
            mem = self._gdn(self.fla_norm(post_attn))     # (B, T, d)
            out_h = post_attn + mem
        else:
            m_vecs = self.compress(post_attn)             # (B, M, d_v)
            mem = self._gdn(self.fla_norm(m_vecs))        # (B, M, d_v)
            read_mem = self.prev_mem if self.prev_mem is not None else torch.zeros_like(mem)
            r = self.decompress(self.read_norm(post_attn), read_mem)
            self.prev_mem = mem
            out_h = post_attn + r

        if isinstance(output, tuple):
            return (out_h,) + output[1:]
        return out_h

    def _forward_parallel(self, hidden_states, *args, **kwargs):
        S, T, M = self._p_S, self._p_T, self._p_M
        B, L, _ = hidden_states.shape
        assert L == S * T, f"parallel: got L={L}, expected S*T={S*T}"

        output = self._call_base_layer(
            hidden_states, args, kwargs, attn_override=self._p_attn_mask
        )
        post_attn = output[0] if isinstance(output, tuple) else output

        if self.write_mode == 'identity':
            # GDN over (B, S*T, d) — parallel scan is bit-equivalent to S
            # sequential calls of length T.
            mem = self._gdn(self.fla_norm(post_attn))
            out_h = post_attn + mem
        else:
            m_vecs = self.compress.parallel(post_attn, S, T, M)   # (B, S*M, d_v)
            mem = self._gdn(self.fla_norm(m_vecs))                # (B, S*M, d_v)
            # Shifted read: segment s reads block s-1 of mem; segment 0 reads
            # prev_mem (carried from a prior call) or zeros.
            d_v = mem.shape[-1]
            B = mem.shape[0]
            first_block = (
                self.prev_mem
                if self.prev_mem is not None
                else mem.new_zeros((B, M, d_v))
            )
            mem_shifted = torch.cat([first_block, mem[:, :(S - 1) * M]], dim=1)
            r = self.decompress.parallel(self.read_norm(post_attn), mem_shifted, S, T, M)
            self.prev_mem = mem[:, (S - 1) * M:].contiguous()
            out_h = post_attn + r

        if isinstance(output, tuple):
            return (out_h,) + output[1:]
        return out_h


class RecurrentMemoryConfig(PretrainedConfig):
    model_type = "rmm"

    def __init__(
        self,
        base_model_name="NousResearch/Llama-3.2-1B",
        base_model_config=None,
        from_pretrained=None,
        fla_layer_name="GatedDeltaNet",
        num_heads=1,
        head_dim=64,
        expand_v=2.0,
        conv_size=4,
        use_short_conv=True,
        state_size=32,
        write_mode='cross_attn',
        read_mode='cross_attn',
        use_parallel_prefill=True,
        eval_stream_logits=False,
        num_memory_vectors=1,
        write_value_dim=None,
        num_memory_heads=1,
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
        self.state_size = state_size
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.use_parallel_prefill = use_parallel_prefill
        self.eval_stream_logits = eval_stream_logits
        self.num_memory_vectors = num_memory_vectors
        self.write_value_dim = write_value_dim
        self.num_memory_heads = num_memory_heads
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    def get(self, attr, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self):
        return {
            "num_heads": self.num_heads,
            "head_dim": self.head_dim,
            "state_size": self.state_size,
            "expand": self.expand_v,
            "conv_size": self.conv_size,
            "conv_kernel": self.conv_size,
            "use_short_conv": self.use_short_conv,
        }


def _build_block_diag_causal_mask(S, T, device, dtype):
    """(1, 1, S*T, S*T) additive mask: 0 inside same-segment causal triangle, -inf elsewhere."""
    L = S * T
    idx = torch.arange(L, device=device)
    seg = idx // T
    valid = (seg.unsqueeze(0) == seg.unsqueeze(1)) & (idx.unsqueeze(1) >= idx.unsqueeze(0))
    mask = torch.zeros(L, L, device=device, dtype=dtype)
    mask.masked_fill_(~valid, float('-inf'))
    return mask.view(1, 1, L, L)


class RecurrentMemoryCell(nn.Module):
    """Wraps every transformer layer of base_model with RecurrentMemoryLayerWrapper."""

    @staticmethod
    def _get_transformer_layers(base_model):
        if hasattr(base_model, "model"):
            return base_model.model.layers
        if hasattr(base_model, "transformer"):
            return base_model.transformer.h
        raise AttributeError(f"Cannot find transformer layers in {type(base_model).__name__}")

    def __init__(self, base_model, fla_layer_name="GatedDeltaNet",
                 num_memory_vectors=1, write_mode='cross_attn',
                 read_mode='cross_attn', write_value_dim=None,
                 num_memory_heads=1, **fla_layer_kwargs):
        super().__init__()
        self.model = base_model

        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        identity = (write_mode == 'identity')
        gdn_hidden_size = model_hidden_size if identity else (write_value_dim or model_hidden_size)
        model_dtype = next(base_model.parameters()).dtype
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
            # NOTE: no outer WithSkip wrapper. The single residual is at the
            # call site in RecurrentMemoryLayerWrapper.forward (`out_h = post_attn + mem`
            # or `post_attn + r`). See module docstring for the resolved formulas.

            wrapped = RecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer,
                model_hidden_size=model_hidden_size,
                num_memory_vectors=num_memory_vectors,
                write_mode=write_mode,
                read_mode=read_mode,
                write_value_dim=write_value_dim,
                num_memory_heads=num_memory_heads,
            )
            transformer_layers[i] = wrapped

        self._mask_cache = {}

    def _set_parallel(self, on, S=0, T=0, M=0, attn_mask=None):
        for layer in self._get_transformer_layers(self.model):
            layer.parallel_mode = on
            layer._p_S, layer._p_T, layer._p_M = S, T, M
            layer._p_attn_mask = attn_mask

    def _get_mask(self, S, T, device, dtype):
        key = (S, T, device.type, device.index if device.index is not None else -1, dtype)
        m = self._mask_cache.get(key)
        if m is None:
            m = _build_block_diag_causal_mask(S, T, device, dtype)
            self._mask_cache[key] = m
        return m

    def parallel_forward(self, input_ids, S, T, M, pad_mask=None, **kwargs):
        """Run all S segments at once (B, S*T) with block-diag causal mask.

        Bit-equivalent to S sequential recurrent calls because:
          - block-diag ATTN == per-segment ATTN
          - COMPRESS/DECOMPRESS.parallel are block-diagonal
          - GDN parallel scan over S*M (or S*T identity) == S sequential GDN calls
          - position_ids are restarted per segment to match per-segment recurrent
        """
        B = input_ids.shape[0]
        device = input_ids.device
        model_dtype = next(self.model.parameters()).dtype

        base_mask = self._get_mask(S, T, device, model_dtype)   # (1,1,L,L)
        attn_mask = base_mask
        if pad_mask is not None:
            neg = torch.finfo(model_dtype).min
            pad4d = (1.0 - pad_mask.to(model_dtype)) * neg
            attn_mask = base_mask + pad4d[:, None, None, :]

        # Per-segment restart for position_ids -> matches recurrent's per-call
        # arange(T) default, so positional embeddings match exactly.
        pos_ids = torch.arange(T, device=device).repeat(S).unsqueeze(0).expand(B, -1)

        self._set_parallel(True, S=S, T=T, M=M, attn_mask=attn_mask)
        try:
            out = self.model(
                input_ids=input_ids,
                attention_mask=attn_mask,
                position_ids=pos_ids,
                **kwargs,
            )
        finally:
            self._set_parallel(False)
        return out

    def forward(self, input_ids, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)


class RecurrentMemoryWrapperBase(nn.Module):
    """Splits segments into (context, qt). Context goes through parallel_forward
    when use_parallel_prefill=True; qt always goes through recurrent path.

    With use_parallel_prefill=False, every segment goes recurrent. Both produce
    bit-equivalent logits (verified by tests/test_rmm_v5p3_equivalence.py)."""

    def __init__(self, memory_cell, use_parallel_prefill=True,
                 eval_stream_logits=False, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.use_parallel_prefill = use_parallel_prefill
        self.eval_stream_logits = eval_stream_logits
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None,
                output_hidden_states=None, *args, **kwargs):
        if not segments:
            raise ValueError("requires at least one segment")

        # Memory-frugal eval path: never hold all-segment float logits. Only the
        # recurrent path (no dense prefill) is streamed; guarded to eval mode so
        # training grads are never affected.
        if getattr(self, "eval_stream_logits", False) and not self.training \
                and not (self.use_parallel_prefill and len(segments) > 1):
            return self._forward_stream(
                segments, labels, output_hidden_states=output_hidden_states, **kwargs)

        cell_outputs = []

        if self.use_parallel_prefill and len(segments) > 1:
            context_segs = segments[:-1]
            qt_seg = segments[-1]

            T_list = [s["input_ids"].shape[1] for s in context_segs]
            assert len(set(T_list)) == 1, f"parallel prefill requires uniform T; got {T_list}"
            T = T_list[0]
            S = len(context_segs)
            cat_ids = torch.cat([s["input_ids"] for s in context_segs], dim=1)
            pad_mask = None
            if all("attention_mask" in s for s in context_segs):
                pad_mask = torch.cat([s["attention_mask"] for s in context_segs], dim=1)
                pad_mask = pad_mask.to(device=cat_ids.device)

            layers = RecurrentMemoryCell._get_transformer_layers(self.memory_cell.model)
            M = layers[0].num_memory_vectors

            ctx_out = self.memory_cell.parallel_forward(
                cat_ids, S=S, T=T, M=M, pad_mask=pad_mask,
                output_hidden_states=True,
            )
            cell_outputs.append(ctx_out)

            qt_out = self.memory_cell(
                input_ids=qt_seg["input_ids"],
                attention_mask=qt_seg.get("attention_mask"),
                output_hidden_states=True,
            )
            cell_outputs.append(qt_out)
        else:
            for seg in segments:
                seg_out = self.memory_cell(
                    input_ids=seg["input_ids"],
                    attention_mask=seg.get("attention_mask"),
                    output_hidden_states=True,
                )
                cell_outputs.append(seg_out)

        labels_mask = None
        if "labels_mask" in segments[0]:
            labels_mask = torch.cat([s["labels_mask"] for s in segments], dim=1)

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

    def _forward_stream(self, segments, labels, output_hidden_states=None, **kwargs):
        """Memory-frugal recurrent eval (config.eval_stream_logits=True).

        Runs segments recurrently but never accumulates all-segment float
        logits: each segment is argmaxed to (B, T) int predictions on the fly
        (its float logits are freed on the next iteration), and only the final
        segment's float logits are kept, for the loss. Returns `logits` as
        (B, S*T) int predictions -> preprocess_logits_for_metrics must pass 2-D
        logits through unchanged.

        Assumes answer labels live solely in the final segment (babilong
        collate: context labels_mask is all False, the predict-next shift for
        every target is interior to the qt segment). Asserted below, so misuse
        on a task with mid-sequence labels errors loudly rather than silently
        dropping loss terms. output_hidden_states is not supported here (eval
        does not request it)."""
        for s in segments[:-1]:
            if "labels_mask" in s and bool(s["labels_mask"].any()):
                raise RuntimeError(
                    "eval_stream_logits assumes labels only in the final segment, "
                    "but a context segment has labels_mask=True. Disable "
                    "eval_stream_logits for this task.")
        if output_hidden_states:
            raise RuntimeError("eval_stream_logits does not support output_hidden_states")

        preds = []
        last_logits = None
        n = len(segments)
        for i, seg in enumerate(segments):
            seg_out = self.memory_cell(
                input_ids=seg["input_ids"],
                attention_mask=seg.get("attention_mask"),
                output_hidden_states=False,
            )
            lg = seg_out.logits                      # (B, T, V) float, this segment only
            preds.append(lg.argmax(dim=-1))          # (B, T) int; float lg freed next iter
            if i == n - 1:
                last_logits = lg

        out = CausalLMOutputWithCrossAttentions()

        # Loss from the final segment only. Identical to process_outputs over the
        # full concatenation because every unmasked (target) position and its
        # predict-next predecessor lie inside this segment; all context positions
        # are masked out and contribute nothing.
        if labels is not None and last_logits is not None:
            qt = segments[-1]
            shift_logits = last_logits[..., :-1, :]
            shift_labels = qt["labels"][..., 1:]
            flat_logits = shift_logits.reshape(-1, shift_logits.size(-1))
            flat_labels = shift_labels.reshape(-1)
            qt_mask = qt.get("labels_mask")
            if qt_mask is not None:
                shift_mask = qt_mask[..., :-1].reshape(-1)
                flat_logits = flat_logits[shift_mask]
                flat_labels = flat_labels[shift_mask]
            out["loss"] = CrossEntropyLoss()(flat_logits, flat_labels)
        else:
            out["loss"] = torch.tensor(0.0)

        out["logits"] = torch.cat(preds, dim=1)      # (B, S*T) int predictions
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
                device_map="auto" if torch.cuda.is_available() else None,
            )
        else:
            base_config = (
                config.base_model_config
                if config.base_model_config is not None
                else AutoConfig.from_pretrained(config.base_model_name)
            )
            base_model = AutoModelForCausalLM.from_config(base_config).to(device)

        self.rmm_config = config
        memory_cell = RecurrentMemoryCell(
            base_model,
            fla_layer_name=config.fla_layer_name,
            num_memory_vectors=config.num_memory_vectors,
            write_mode=config.write_mode,
            read_mode=config.read_mode,
            write_value_dim=config.write_value_dim,
            num_memory_heads=config.num_memory_heads,
            **config.fla_layer_kwargs(),
        )
        self.rmt = RecurrentMemoryWrapperBase(
            memory_cell,
            use_parallel_prefill=getattr(config, 'use_parallel_prefill', True),
            eval_stream_logits=getattr(config, 'eval_stream_logits', False),
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id,
        )

    def _reset_memory(self):
        for layer in RecurrentMemoryCell._get_transformer_layers(self.rmt.memory_cell.model):
            layer.reset_memory()

    def set_parallel_prefill(self, enabled: bool):
        self.rmt.use_parallel_prefill = bool(enabled)

    @contextmanager
    def recurrent_mode(self):
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
        with self.recurrent_mode():
            return self.rmt.memory_cell.model.generate(*args, **kwargs)

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
