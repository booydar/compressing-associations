"""v5p7-eff: v5p7 with the O(L^2) memory terms of the parallel-prefill path
removed. Mathematically the same model — same parameters, same forward
function — so v5p7 checkpoints load unchanged and the v5p7 equivalence tests
still hold (see tests/test_rmm_v5p7_eff_equivalence.py).

What changed vs huggingface_rmm_v5p7.py, and why
------------------------------------------------
1. SEGMENT-FOLDED ATTENTION (the big one). v5p7 ran the S segments as one
   (B, S*T) sequence under a dense block-diagonal causal mask of shape
   (S*T, S*T). Because a pad mask was almost always supplied, the mask
   acquired a batch dim -> (B, 1, L, L), which in turn forced SDPA off the
   flash path and got materialised at (B, H, L, L). That single tensor is
   what made peak training VRAM grow quadratically in the context length:
   measured 2.0 GB at 3.5k tokens but 20.1 GB at 14.3k (B=8, 4 layers, d=128).

   Block-diagonal causal attention over S segments of T tokens *is* ordinary
   causal attention on (B*S, T, d). So the backbone sublayer now sees the
   segments folded into the batch dimension and no mask at all (is_causal),
   and the memory path still sees the (B, S*T, d) view it needs. Same
   function, no L x L tensor anywhere:

       N=2048 pairs (14.3k tok):  20070 MB -> 4185 MB
       scaling per 2x in N:       3.33x    -> 1.99x   (i.e. linear)

2. NO DENSE MASK IS BUILT AT ALL. parallel_forward passes attention_mask=None
   to the backbone (HF then skips mask construction entirely) and hands the
   layers a (B*S, T) 2-D pad mask only when padding is actually present.
   Keeping the cell-level (B,1,L,L) mask alive while folding the layers still
   cost ~800 MB at 7k tokens, so both had to go.

3. _mask_cache REMOVED. v5p7 memoised masks keyed on (S, T, device, dtype)
   with no eviction: one L^2 tensor per distinct shape, pinned for the life of
   the model (390 MB each at L=14k under a varying-S curriculum).

4. OPT-IN stream_context_logits (default False). Skips ever materialising the
   (B, S*T, vocab) float logits of the context: the context LM head runs under
   no_grad in chunks and is argmaxed on the fly, only the QT segment keeps
   float logits (which is where the loss lives). Negligible at the benchmark's
   vocab=70, decisive at Llama's 128k vocab where that tensor alone is ~29 GB
   at B=8/L=14k. Requires context labels to be fully masked; asserted.
   Returned `logits` are then (B, S*T) ints, as in v5p7_streameval, so
   preprocess_logits_for_metrics must pass 2-D logits through unchanged.

5. OPT-IN eval_stream_logits (default False). Ported verbatim from
   huggingface_rmm_v5p7_streameval.py: the same trick for the pure-recurrent
   eval path. Complements (4), which covers the parallel path.

6. process_outputs no longer concatenates every layer's hidden states unless
   output_hidden_states was actually requested, and the two internal call
   sites stop requesting them unconditionally.

Defaults (1)-(3) and (6) are always on. Folding switches SDPA from the
mem-efficient+bias kernel to the flash is_causal kernel, so bitwise identity is
not guaranteed in principle — but measured in fp32 on both GPT-2 and Llama
backbones, in both execution forms, logits AND gradients come out at exactly
0.0 max-abs difference from v5p7 (in bf16 the loss moves by ~2e-4, ordinary
kernel-reordering noise). (4) and (5) are off by default, so out of the box
this module is a drop-in v5p7.

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
        # (B*S, 1, T, T) additive causal+pad mask for the folded parallel path,
        # or None when the batch is unpadded (the common case) -> is_causal.
        self._p_seg_pad = None

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

    # Cap on how many folded rows go into one backbone call; above it the call is
    # split and the outputs concatenated (segments are independent inside a layer,
    # so this is exact). Two separate reasons to bound it:
    #
    #  1. CUDA caps a grid dimension at 65535 and the folded call puts B*S there.
    #     Hit for real at T=7, N=16384 pairs, B=8 -> B*S = 131064, which dies with
    #     'invalid configuration argument'.
    #  2. The attention kernel's per-sequence workspace is quantised to a block
    #     size, so at very small T a huge batch of short rows pays for far more
    #     than it uses. Measured at T=1, N=512, B=8 (28664 rows): unbounded costs
    #     2732 MB, 8192 costs 1476 MB (-46%) for +5% wall-clock. Chunking finer
    #     keeps helping (1246 MB at 4096) but the time cost climbs steeply
    #     (+32%), and at T>=7 there is nothing left to recover — 8192 is the knee.
    #
    # Rows below the cap take the single-call path and are unaffected.
    MAX_FOLD_ROWS = 8192

    def _call_base_layer_folded(self, hidden_states, args, kwargs, B, S, T, d):
        """Run base_layer on (B*S, T, d) instead of (B, S*T, d).

        Attention becomes plain causal attention within each segment, which is
        what the block-diagonal mask encoded — but without an L x L tensor, and
        on the flash kernel. Anything the caller passed that is indexed by the
        (B, S*T) sequence layout has to be re-folded to match:

          attention_mask     -> the (B*S, T) pad mask, or None (is_causal)
          position_ids       -> arange(T), already per-segment in v5p7
          position_embeddings-> (B, S*T, hd) -> (B*S, T, hd); v5p7 restarts
                                positions per segment, so this is a pure view
          cache_position     -> sliced to the first segment's T entries

        Returns whatever base_layer returns, with the leading dim still B*S.
        """
        names = self._base_param_names
        merged = {**dict(zip(names[1:1 + len(args)], args)), **kwargs}

        merged['attention_mask'] = self._p_seg_pad     # None unless padded

        if merged.get('position_ids') is not None:
            merged['position_ids'] = torch.arange(
                T, device=hidden_states.device
            ).unsqueeze(0).expand(B * S, -1)

        pe = merged.get('position_embeddings')
        if pe is not None:
            cos, sin = pe
            hd = cos.shape[-1]
            merged['position_embeddings'] = (
                cos.expand(B, S * T, hd).reshape(B * S, T, hd),
                sin.expand(B, S * T, hd).reshape(B * S, T, hd),
            )

        cp = merged.get('cache_position')
        if cp is not None and cp.shape[0] == S * T:
            merged['cache_position'] = cp[:T]

        folded = hidden_states.reshape(B * S, T, d)
        rows = folded.shape[0]
        if rows <= self.MAX_FOLD_ROWS:
            return self.base_layer(folded, **merged)

        # Chunk over rows so no kernel launch exceeds the CUDA grid limit. The
        # row-indexed kwargs have to be sliced along with the hidden states, and
        # the backbone KV cache has to be switched off: it is shared across the
        # calls, so each chunk would otherwise append to what the previous chunk
        # wrote and blow up on a batch mismatch. The parallel path discards that
        # cache regardless (cross-segment state travels through the GDN).
        outs, was_tuple = [], False
        for i in range(0, rows, self.MAX_FOLD_ROWS):
            sl = slice(i, min(i + self.MAX_FOLD_ROWS, rows))
            chunk_kwargs = dict(merged)
            chunk_kwargs['use_cache'] = False
            for k in ('past_key_value', 'past_key_values'):
                if k in chunk_kwargs:
                    chunk_kwargs[k] = None
            if chunk_kwargs.get('attention_mask') is not None:
                chunk_kwargs['attention_mask'] = merged['attention_mask'][sl]
            if chunk_kwargs.get('position_ids') is not None:
                chunk_kwargs['position_ids'] = merged['position_ids'][sl]
            if chunk_kwargs.get('position_embeddings') is not None:
                c, s_ = merged['position_embeddings']
                chunk_kwargs['position_embeddings'] = (c[sl], s_[sl])
            o = self.base_layer(folded[sl], **chunk_kwargs)
            was_tuple = isinstance(o, tuple)
            outs.append(o[0] if was_tuple else o)
        out = torch.cat(outs, dim=0)
        return (out,) if was_tuple else out

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
        B, L, d = hidden_states.shape
        assert L == S * T, f"parallel: got L={L}, expected S*T={S*T}"

        # --- backbone sublayer: fold segments into the batch dim ---------------
        # Block-diagonal causal attention over S segments of T tokens is exactly
        # plain causal attention on (B*S, T, d). Folding avoids the (B, H, L, L)
        # mask v5p7 had to materialise, and re-enables the flash SDPA kernel.
        # Everything in a decoder layer other than attention is position-wise,
        # so the fold is transparent to it.
        output = self._call_base_layer_folded(hidden_states, args, kwargs, B, S, T, d)
        post_attn = output[0] if isinstance(output, tuple) else output
        post_attn = post_attn.reshape(B, L, d)

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
        stream_context_logits=False,
        logits_chunk_tokens=4096,
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
        self.stream_context_logits = stream_context_logits
        self.logits_chunk_tokens = logits_chunk_tokens
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


# NOTE: v5p7's `_build_block_diag_causal_mask` is intentionally absent. The
# block-diagonal mask is expressed structurally now (fold S into the batch dim,
# see RecurrentMemoryLayerWrapper._call_base_layer_folded), which is the whole
# point of this module: no S*T x S*T tensor is ever allocated.


def _build_folded_pad_mask(pad_mask, B, S, T, device, dtype):
    """Additive (B*S, 1, T, T) causal+padding mask for the folded parallel path.

    Only needed when the batch is genuinely padded — an unpadded batch passes
    attention_mask=None and takes SDPA's is_causal fast path instead. Because we
    call the decoder layers directly we also bypass HF's 2-D -> 4-D mask
    conversion, so causality has to be baked in here.

    Size is B*S*T^2 = B*L*T, i.e. LINEAR in the context length (6.4 MB at
    B=8/L=14k/T=28), which is the entire difference from v5p7's B*L^2.
    """
    neg = torch.finfo(dtype).min
    causal = torch.triu(torch.full((T, T), neg, device=device, dtype=dtype), diagonal=1)
    pad = (1.0 - pad_mask.reshape(B * S, T).to(dtype)) * neg
    return causal[None, None] + pad[:, None, None, :]


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

        # NOTE: v5p7's `self._mask_cache` is gone on purpose. It memoised an
        # (S*T, S*T) tensor per distinct (S, T, device, dtype) and never evicted,
        # so a curriculum that varies the segment count pinned one L^2 tensor per
        # shape for the life of the model. Nothing to cache now.

    def _set_parallel(self, on, S=0, T=0, M=0, seg_pad=None):
        for layer in self._get_transformer_layers(self.model):
            layer.parallel_mode = on
            layer._p_S, layer._p_T, layer._p_M = S, T, M
            layer._p_seg_pad = seg_pad

    def parallel_forward(self, input_ids, S, T, M, pad_mask=None, **kwargs):
        """Run all S segments at once (B, S*T), segments folded into the batch.

        Equivalent to S sequential recurrent calls because:
          - per-segment causal ATTN on (B*S, T) == block-diag ATTN on (B, S*T)
          - COMPRESS/DECOMPRESS.parallel are block-diagonal
          - GDN parallel scan over S*M (or S*T identity) == S sequential GDN calls
          - position_ids are restarted per segment to match per-segment recurrent

        Unlike v5p7 this allocates no S*T x S*T mask: `attention_mask=None` goes
        to the backbone (HF skips mask construction entirely for a plain causal
        sdpa model), and the layers get a (B*S, T) 2-D pad mask only if the batch
        is genuinely padded. Peak train VRAM becomes linear in S*T.
        """
        B = input_ids.shape[0]
        device = input_ids.device

        # Only pay for a pad mask if something is actually masked out. The
        # all-ones case is by far the common one (fixed-length KV segments).
        seg_pad = None
        if pad_mask is not None and not bool(pad_mask.all()):
            seg_pad = _build_folded_pad_mask(
                pad_mask, B, S, T, input_ids.device,
                next(self.model.parameters()).dtype)

        # Per-segment restart for position_ids -> matches recurrent's per-call
        # arange(T) default, so positional embeddings match exactly.
        pos_ids = torch.arange(T, device=device).repeat(S).unsqueeze(0).expand(B, -1)

        self._set_parallel(True, S=S, T=T, M=M, seg_pad=seg_pad)
        try:
            out = self.model(
                input_ids=input_ids,
                attention_mask=None,
                position_ids=pos_ids,
                **kwargs,
            )
        finally:
            self._set_parallel(False)
        return out

    def parallel_forward_no_head(self, input_ids, S, T, M, pad_mask=None, **kwargs):
        """As parallel_forward, but stops before the LM head.

        Used by stream_context_logits: the context's float logits are never
        needed as a whole, so we take the backbone hidden states and let the
        caller run the head in chunks. Returns (B, S*T, d_model)."""
        inner = None
        for attr in ("model", "transformer"):          # llama-style, gpt2-style
            if hasattr(self.model, attr):
                inner = getattr(self.model, attr)
                break
        if inner is None:
            raise AttributeError(
                f"Cannot find the headless backbone inside {type(self.model).__name__}")
        B = input_ids.shape[0]
        device = input_ids.device
        seg_pad = None
        if pad_mask is not None and not bool(pad_mask.all()):
            seg_pad = _build_folded_pad_mask(
                pad_mask, B, S, T, input_ids.device,
                next(self.model.parameters()).dtype)
        pos_ids = torch.arange(T, device=device).repeat(S).unsqueeze(0).expand(B, -1)
        self._set_parallel(True, S=S, T=T, M=M, seg_pad=seg_pad)
        try:
            out = inner(
                input_ids=input_ids,
                attention_mask=None,
                position_ids=pos_ids,
                **kwargs,
            )
        finally:
            self._set_parallel(False)
        return out[0] if isinstance(out, tuple) else out.last_hidden_state

    def forward(self, input_ids, **kwargs):
        return self.model(input_ids=input_ids, **kwargs)


class RecurrentMemoryWrapperBase(nn.Module):
    """Splits segments into (context, qt). Context goes through parallel_forward
    when use_parallel_prefill=True; qt always goes through recurrent path.

    With use_parallel_prefill=False, every segment goes recurrent. Both produce
    bit-equivalent logits (verified by tests/test_rmm_v5p3_equivalence.py)."""

    def __init__(self, memory_cell, use_parallel_prefill=True,
                 eval_stream_logits=False, stream_context_logits=False,
                 logits_chunk_tokens=4096, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.use_parallel_prefill = use_parallel_prefill
        self.eval_stream_logits = eval_stream_logits
        self.stream_context_logits = stream_context_logits
        self.logits_chunk_tokens = logits_chunk_tokens
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None,
                output_hidden_states=None, *args, **kwargs):
        if not segments:
            raise ValueError("requires at least one segment")

        # Memory-frugal recurrent eval (ported from v5p7_streameval). Guarded to
        # eval mode so training grads are never affected.
        if getattr(self, "eval_stream_logits", False) and not self.training \
                and not (self.use_parallel_prefill and len(segments) > 1):
            return self._forward_stream(
                segments, labels, output_hidden_states=output_hidden_states, **kwargs)

        # Memory-frugal parallel prefill: never materialise the context's
        # (B, S*T, vocab) float logits. Works in train mode too, because with
        # a fully-masked context those logits carry no gradient to the loss.
        if getattr(self, "stream_context_logits", False) \
                and self.use_parallel_prefill and len(segments) > 1:
            return self._forward_parallel_stream(
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

            if output_hidden_states:
                raise NotImplementedError(
                    "v5p7_eff: output_hidden_states is not supported on the "
                    "parallel-prefill path — with segments folded into the batch "
                    "dim the backbone reports (B*S, T, d) states. Use "
                    "use_parallel_prefill=False if you need them.")

            ctx_out = self.memory_cell.parallel_forward(
                cat_ids, S=S, T=T, M=M, pad_mask=pad_mask,
                output_hidden_states=False,
            )
            cell_outputs.append(ctx_out)

            qt_out = self.memory_cell(
                input_ids=qt_seg["input_ids"],
                attention_mask=qt_seg.get("attention_mask"),
                output_hidden_states=bool(output_hidden_states),
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
        # v5p7 built the all-layer concatenation unconditionally; here it is only
        # paid for when the caller actually asked (it pins (n_layers+1) tensors of
        # (B, S*T, d) and, under transformers>=4.57, keeps the recorder's per-layer
        # captures alive with them).
        if kwargs.get("output_hidden_states"):
            out["hidden_states"] = tuple(
                torch.cat(layer_hs, dim=1)
                for layer_hs in zip(*[o.hidden_states for o in cell_outputs])
            )
        return out

    def _forward_stream(self, segments, labels, output_hidden_states=None, **kwargs):
        """Memory-frugal recurrent eval (config.eval_stream_logits=True).

        Ported unchanged from huggingface_rmm_v5p7_streameval.py. Runs segments
        recurrently but never accumulates all-segment float logits: each segment
        is argmaxed to (B, T) int predictions on the fly (its float logits are
        freed on the next iteration), and only the final segment's float logits
        are kept, for the loss. Returns `logits` as (B, S*T) int predictions ->
        preprocess_logits_for_metrics must pass 2-D logits through unchanged.

        Assumes answer labels live solely in the final segment (babilong
        collate). Asserted below, so misuse on a task with mid-sequence labels
        errors loudly rather than silently dropping loss terms."""
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
        out["loss"] = self._qt_loss(last_logits, segments[-1], labels)
        out["logits"] = torch.cat(preds, dim=1)      # (B, S*T) int predictions
        return out

    def _forward_parallel_stream(self, segments, labels, output_hidden_states=None, **kwargs):
        """Memory-frugal parallel prefill (config.stream_context_logits=True).

        Identical memory semantics to the default parallel path — one fused pass
        over the S context segments, then the QT segment recurrently — but the
        context never has its (B, S*T, vocab) float logits materialised. The
        backbone stops before the LM head; the head is then applied under
        no_grad in chunks of `logits_chunk_tokens` and argmaxed immediately, so
        peak logits memory is one chunk instead of the whole context.

        Dropping the context's gradient path is exact, not an approximation:
        this path requires every context `labels_mask` to be all-False (asserted
        below), and a fully-masked position contributes nothing to the loss.

        Returns `logits` as (B, S*T + T_qt) int predictions, matching
        _forward_stream's contract."""
        for s in segments[:-1]:
            if "labels_mask" in s and bool(s["labels_mask"].any()):
                raise RuntimeError(
                    "stream_context_logits assumes labels only in the final segment, "
                    "but a context segment has labels_mask=True. Disable "
                    "stream_context_logits for this task.")
        if output_hidden_states:
            raise RuntimeError("stream_context_logits does not support output_hidden_states")

        context_segs, qt_seg = segments[:-1], segments[-1]
        T_list = [s["input_ids"].shape[1] for s in context_segs]
        assert len(set(T_list)) == 1, f"parallel prefill requires uniform T; got {T_list}"
        T, S = T_list[0], len(context_segs)
        cat_ids = torch.cat([s["input_ids"] for s in context_segs], dim=1)
        pad_mask = None
        if all("attention_mask" in s for s in context_segs):
            pad_mask = torch.cat([s["attention_mask"] for s in context_segs],
                                 dim=1).to(device=cat_ids.device)

        layers = RecurrentMemoryCell._get_transformer_layers(self.memory_cell.model)
        M = layers[0].num_memory_vectors

        # Backbone only; memory state is written exactly as in parallel_forward.
        hidden = self.memory_cell.parallel_forward_no_head(
            cat_ids, S=S, T=T, M=M, pad_mask=pad_mask)

        lm_head = self.memory_cell.model.get_output_embeddings()
        chunk = max(int(self.logits_chunk_tokens), 1)
        preds = []
        with torch.no_grad():
            for i in range(0, hidden.shape[1], chunk):
                preds.append(lm_head(hidden[:, i:i + chunk]).argmax(dim=-1))
        del hidden

        qt_out = self.memory_cell(
            input_ids=qt_seg["input_ids"],
            attention_mask=qt_seg.get("attention_mask"),
            output_hidden_states=False,
        )
        preds.append(qt_out.logits.argmax(dim=-1))

        out = CausalLMOutputWithCrossAttentions()
        out["loss"] = self._qt_loss(qt_out.logits, qt_seg, labels)
        out["logits"] = torch.cat(preds, dim=1)
        return out

    @staticmethod
    def _qt_loss(qt_logits, qt_seg, labels):
        """Loss from the QT segment alone.

        Identical to process_outputs over the full concatenation whenever every
        unmasked target and its predict-next predecessor lie inside the QT
        segment (guaranteed by the all-False context labels_mask that both
        streaming paths assert)."""
        if labels is None or qt_logits is None:
            return torch.tensor(0.0)
        shift_logits = qt_logits[..., :-1, :]
        shift_labels = qt_seg["labels"][..., 1:]
        flat_logits = shift_logits.reshape(-1, shift_logits.size(-1))
        flat_labels = shift_labels.reshape(-1)
        qt_mask = qt_seg.get("labels_mask")
        if qt_mask is not None:
            shift_mask = qt_mask[..., :-1].reshape(-1)
            flat_logits = flat_logits[shift_mask]
            flat_labels = flat_labels[shift_mask]
        return CrossEntropyLoss()(flat_logits, flat_labels)

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
            stream_context_logits=getattr(config, 'stream_context_logits', False),
            logits_chunk_tokens=getattr(config, 'logits_chunk_tokens', 4096),
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
