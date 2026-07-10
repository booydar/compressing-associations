"""v6p5: fork of v6p4. Replaces the "dumb" single-op LlamaCrossAttention used by the
``cross_attn`` write/read modes with a FULL transformer decoder layer (the SAME class
the training script builds the from-scratch backbone from, e.g. LlamaDecoderLayer /
GPT2Block) run in CROSS-ATTENTION mode -- i.e. attention + MLP + internal residuals +
norms, "full transformer power", to test whether that closes the cross_attn gap vs
identity (see project_rmm_babi_pool_vs_identity).

New modes: write_mode='cross_attn_tf' and read_mode='cross_attn_tf'. Mechanics
(``CrossTransformerBlock``): a fresh decoder layer is built from a deepcopy of the base
config (forced to attn_implementation='eager' so it honors our additive mask). Per call
we concat [kv ; query] (query LAST) and apply an additive mask that makes the query
columns un-attendable, so the query rows perform pure cross-attention over kv (same
CONNECTIVITY as the old LlamaCrossAttention; GPT2's intrinsic causal bias is harmless
because kv always precedes the queries). RoPE (when the arch uses it) is applied over
the concat via the base model's rotary embedding. Block-diagonal over segments => the
parallel path stays bit-equivalent to S recurrent calls. cross_attn_tf requires
write_value_dim == model_hidden_size (the decoder layer runs in model_hidden_size). On
the read side read_norm is set to Identity so out_h = post_attn + (layer_out - post_attn)
== a real decoder layer applied to post_attn. The inherited v6p4 docstring follows.

v6p4: fork of v6p3. Adds (a) multi-head write cross-attention (num_memory_heads,
unifying the write side with the read side) and (b) cross-layer query threading:
layer 0 uses the trainable query banks; layers >0 reuse the PREVIOUS layer's memory
(write m_vecs / read g) as queries, threaded through a shared `thread_state` dict
(ARMT-style depth refinement). Gated by config.thread_memory (default True); set False
to recover v6p3 behaviour exactly. The inherited v6p3 docstring follows.

v6p3: fork of v6p2 that FIXES the silently-dropped GDN config (plumbing only;
read/write logic identical to v6p2).

BUG (v6p0-v6p2): RecurrentMemoryCell filtered fla_layer_kwargs by
`inspect.signature(ReadAwareGatedDeltaNet.__init__)`, but that wrapper is declared
`__init__(self, *args, **kwargs)` -> signature params are just {self,args,kwargs}, so
EVERY GDN knob (num_heads/head_dim/expand_v/conv_size) matched nothing and was dropped.
The GDN was built with pure FLA defaults (head_dim 256, num_heads 6, ~786k state/layer);
`state_size` did nothing (ss16 == ss32). Confirmed in notebooks/debug_rmmv5.ipynb.

v6p3 FIX:
  * `RecurrentMemoryConfig.fla_layer_kwargs()` emits only keys FLA accepts
    (num_heads, head_dim, expand_v, conv_size, use_short_conv). `state_size` is encoded
    via head_dim = state_size // num_heads (set by the runner); FLA has no state_size.
  * RecurrentMemoryCell filters against the REAL `fla.layers.<name>` signature (the
    ReadAware wrapper forwards **kwargs to it) and HARD-ERRORS on any requested knob the
    FLA class won't accept -- no more silent fallback.
  * Logs the resolved GDN geometry once at build and asserts num_heads/head_k_dim match.

Nothing else changes vs v6p2 (multi-head unify and cross-layer threading land in v6p4).

Original v6p2 docstring follows.

---

v6p2: identity-read with a conv gap between reads and writes (fork of v6p0).

v6p0's identity-read runs one GDN scan over ``[reads(T), writes(M)]``. The causal
short conv (width ``conv_size``) lets the last ``conv_size-1`` read tokens bleed
into the first write tokens' k/v, so raw segment tokens leak into the written
recurrent_state — partly bypassing the compress bottleneck (measured 60-99% state
sensitivity to read content on a trained ckpt).

v6p2 inserts ``gap_width`` zero, read-masked tokens between the reads and the
writes: ``[reads(T) | gap(G) | writes(M)]``. With ``G >= conv_size-1`` the write
tokens' conv window can no longer reach any read token, so the written state is a
pure function of the compressed writes (conv-leak probe -> 0). The gap tokens are
zeros (contribute nothing to the conv) and valved (read_mask True -> beta=0, they
never write/decay the state). Default ``G = conv_size + 1``.

Unlike v6p1 (which split the scan into a per-segment read-fork + write-only loop,
correct but ~4x slower because it loses parallel-prefill batching), v6p2 keeps the
SINGLE batched GDN scan, so parallel-prefill speed is preserved. Only the
identity-read branches change; pool/unpool and identity-write are untouched.

Intentional residual: a write still bleeds into the NEXT segment's read query via
cross-segment conv (same as v6p0). That doesn't touch the state bottleneck (reads
are valved; state stays clean) — it only conv-flavors a read query with info
already in the state. Removing it would need fresh per-segment conv = the v6p1
loop = the 4x. So it's left as-is.

Original v6p0 docstring follows.

---

v6p0: disentangled read/write memory (clean fork of v5p7).

v5p7's compressed path tangled read and write: tokens read ``prev_mem`` — the
GDN output of the *previous* segment's *write* vectors. That read was
content-blind, one-segment stale, and tied to the write queries.

v6p0 separates the read from the write while keeping the four operations
(compress -> write -> read -> decompress). Per layer, per segment s:

    H      = BaseLayer(x)                     # T x d
    m      = Compress(H)         M x d_m      # WRITE vectors  (write_mode)
    # one shared GDN scan over [R read queries, M write vectors] per segment:
    #   read tokens  : beta=0, decay=1 -> read S_{s-1}, do NOT write/decay it
    #   write tokens : normal          -> S_{s-1} -> S_s
    g      = GDN read outputs    R x d_m      # gated read of S_{s-1}
    r      = Decompress(H, g)    T x d        # tokens read the R read vectors
    out    = H + r

Key differences vs v5p7:
  * Dedicated static ``read_queries`` (R x d_m), separate from the write queries.
    These ARE the read tokens; they read the state, they do not attend H.
  * The read is a set of read-only tokens placed *before* the write tokens in the
    SAME GDN scan, so they read the fresh pre-segment state S_{s-1}.
  * ``prev_mem`` and the manual ``mem_shifted`` shift are removed — the one-segment
    shift is now implicit in sequence order, and cross-segment carry happens
    entirely through the GDN cache (recurrent_state + conv_state).
  * Read-only positions use beta=0 / decay=1 via ``ReadAwareGatedDeltaNet`` so they
    never write or decay the state; GDN's own output gate on those positions is
    inherited (the "skip-read valve").
  * Conv stays ON (causal -> no leak). Decompress is unchanged except its K/V
    source is ``g`` (R read vectors) instead of ``prev_mem``.

identity mode (write_mode == read_mode == 'identity') is preserved exactly as in
v5p7 (GDN runs directly on the T tokens, no compression, no read_queries) — it is
the uncompressed baseline and has no decompress to feed ``g`` into.

identity READ (write_mode in {pool, cross_attn}, read_mode == 'identity') ports
v5p5/v5p6's state-pure identity read into the v6p0 valve: the read positions are
the T post-attn tokens themselves (each reads S_{s-1} via its own GDN query), the
M compressed writes advance the state, and the read outputs feed the residual
directly (no decompress). Unlike v5p6 this needs no cache fork/snapshot — the
read-only valve (beta=0, decay=1) keeps the read state-pure inside one GDN scan,
so gradients flow natively and parallel ≡ recurrent. The one behavioral change
vs v5p6: read tokens do NOT see each other through the GDN (beta=0 -> no write to
state), since within-segment token mixing is already handled by the base layer's
causal attention.

Parallel-prefill is bit-equivalent (within kernel tolerance) to S sequential
recurrent calls. The interleaved [R reads, M writes] layout is contiguous and
identical between the two paths, and the read_mask is applied per-position, so
the GDN scan equivalence carries over from v5p7.

INVARIANTS (tests/):
  * test_rmm_v6p0_readonly.py    — read tokens leave GDN recurrent_state unchanged
                                    and read S_{s-1} (pre-write state).
  * test_rmm_v6p0_equivalence.py — parallel-prefill logits == recurrent logits.

FLA note: this FLA build passes the raw ``a_proj`` pre-activation into the kernel
(``use_gate_in_kernel=True``) rather than exposing a pre-computed log-decay, so
"no decay" is achieved by masking ``a_proj``'s output to a large negative value
(softplus -> 0 -> decay = 1), not by masking it to 0. See ReadAwareGatedDeltaNet.
"""
from __future__ import annotations

import copy
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


class ReadAwareGatedDeltaNet(fla.layers.GatedDeltaNet):
    """GDN where 'read' positions (``read_mask`` True) neither write nor decay state.

    Realizes the v6p0 read-only valve WITHOUT copying GDN.forward (robust to FLA
    version drift). For read positions:
      beta  -> 0  : mask ``b_proj`` pre-sigmoid output to a large negative number so
                    ``sigmoid(.) -> 0``  => no delta write.
      decay -> 1  : mask ``a_proj`` output (the gate pre-activation handed to the
                    kernel as ``g``) to a large negative number so ``softplus(.) -> 0``
                    => g_eff -> 0 => ``exp(g_eff) -> 1`` => state not forgotten.

    Implemented with forward-hooks on ``a_proj``/``b_proj`` keyed off a per-call
    ``read_mask``. The hooks only touch the gate (a) and write-strength (b)
    projections; q/k/v/conv/output-gate are left untouched, so read tokens still
    produce a faithful gated readout of the state through the GDN machinery.
    """

    # Saturates both sigmoid and softplus to exactly 0 in fp16 / bf16 / fp32.
    _NEG = -1e4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._read_mask = None  # (B, L) bool; True at read positions
        self.a_proj.register_forward_hook(self._read_mask_hook)
        self.b_proj.register_forward_hook(self._read_mask_hook)

    def _read_mask_hook(self, module, inputs, output):
        rm = self._read_mask
        if rm is None:
            return output
        # output: (B, L, num_v_heads); rm: (B, L) -> broadcast over the head dim.
        return output.masked_fill(rm.unsqueeze(-1), self._NEG)

    def forward(self, hidden_states, *args, read_mask=None, **kwargs):
        self._read_mask = read_mask
        try:
            return super().forward(hidden_states, *args, **kwargs)
        finally:
            self._read_mask = None


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


class CrossTransformerBlock(nn.Module):
    """v6p5: a FULL transformer decoder layer (same class as the backbone, freshly
    built from the base config) run in CROSS-ATTENTION mode. Drop-in replacement for
    the bare LlamaCrossAttention used by the cross_attn write/read modes, adding the
    layer's MLP + internal residuals + norms ("full transformer power").

    Layout per call: concat [kv(K) ; query(Q)] with query LAST. An additive mask makes
    the Q query columns un-attendable, so EVERY row attends only to the K kv columns ->
    the Q query rows do pure cross-attention over kv (same connectivity as
    LlamaCrossAttention). GPT2's intrinsic eager causal bias is harmless: kv always
    precedes the queries, so a query row's allowed (causal) keys already include all kv,
    and the mask removes the query columns. Llama eager applies only our mask. We read
    out the Q query rows.

    subtract_query=True  -> return (layer_out_q - query): the residual DELTA, so the
                            caller's out_h = post_attn + delta == a real decoder layer
                            applied to post_attn (read / decompress side).
    subtract_query=False -> return layer_out_q directly (write side; queries are the
                            learnable / threaded memory slots, the layer output IS the
                            written memory content).

    Stateless (no KV cache); block-diagonal `parallel` folds S segments into the batch
    so it is bit-equivalent to S sequential `forward` calls.
    """

    def __init__(self, base_layer_cls, base_config, base_rotary, subtract_query):
        super().__init__()
        if base_layer_cls is None or base_config is None:
            raise ValueError("CrossTransformerBlock needs base_layer_cls and base_config "
                             "(threaded from RecurrentMemoryCell). cross_attn_tf is only "
                             "available through the full RMM build path.")
        cfg = copy.deepcopy(base_config)
        # eager so the layer honors our additive 4D mask deterministically across archs.
        cfg._attn_implementation = "eager"
        try:
            self.layer = base_layer_cls(cfg, layer_idx=0)
        except TypeError:
            self.layer = base_layer_cls(cfg)
        # Shared, stateless rotary from the base model (None for non-RoPE archs e.g. GPT2,
        # which inject absolute positions upstream at the embedding level).
        self.rotary = base_rotary
        self.subtract_query = subtract_query

    def _core(self, query, kv):
        b, Q, d = query.shape
        K = kv.shape[1]
        seq = torch.cat([kv, query], dim=1)            # (b, K+Q, d), query LAST
        L = K + Q
        neg = torch.finfo(seq.dtype).min
        mask = seq.new_zeros(1, 1, L, L)
        mask[..., K:] = neg                            # query columns un-attendable
        if self.rotary is not None:
            pos = torch.arange(L, device=seq.device).unsqueeze(0).expand(b, L)
            cos, sin = self.rotary(seq, pos)
            out = self.layer(seq, attention_mask=mask,
                             position_embeddings=(cos, sin), use_cache=False)
        else:
            out = self.layer(seq, attention_mask=mask, use_cache=False)
        out = out[0] if isinstance(out, tuple) else out
        q_out = out[:, K:, :]                          # (b, Q, d)
        if self.subtract_query:
            q_out = q_out - query
        return q_out

    def forward(self, query, kv):
        return self._core(query, kv)

    def parallel(self, query, kv, S):
        """query (b, S*Q, d), kv (b, S*K, d) -> (b, S*Q, d). Block-diagonal: each
        segment's Q queries attend only to its own K kv. Folding S into the batch
        makes this bit-equivalent to S sequential `forward` calls."""
        b, _, d = query.shape
        Q = query.shape[1] // S
        K = kv.shape[1] // S
        q = query.reshape(b * S, Q, d)
        k = kv.reshape(b * S, K, d)
        out = self._core(q, k)                         # (b*S, Q, d)
        return out.reshape(b, S * Q, d)


class MemoryCompress(nn.Module):
    """T tokens per segment -> M memory vectors per segment.

    forward(h):              (B, T, d) -> (B, M, d_v)
    parallel(h, S, T, M):    (B, S*T, d) -> (B, S*M, d_v)

    The parallel call is block-diagonal: segment i's M queries attend only
    to tokens [i*T:(i+1)*T]. Bit-equivalent to S sequential forward() calls.
    """

    def __init__(self, hidden_size, num_vectors, mode='cross_attn',
                 write_value_dim=None, num_heads=1, bias=False,
                 base_layer_cls=None, base_config=None, base_rotary=None):
        super().__init__()
        if mode not in ('pool', 'cross_attn', 'cross_attn_tf'):
            raise ValueError(f"mode must be 'pool'|'cross_attn'|'cross_attn_tf', got '{mode}'")
        self.mode = mode
        self.num_vectors = num_vectors
        self.hidden_size = hidden_size
        self.write_value_dim = write_value_dim or hidden_size
        self.scaling = hidden_size ** -0.5

        # Layer-0 query bank. With cross-layer threading (v6p4) layers >0 pass the
        # previous layer's memory in as `queries` instead of using this bank.
        self.write_queries = nn.Parameter(torch.zeros(num_vectors, hidden_size))
        nn.init.normal_(self.write_queries, std=hidden_size ** -0.5)

        if mode == 'pool':
            self.k_proj = nn.Linear(hidden_size, hidden_size, bias=bias)
            self.v_proj = nn.Linear(hidden_size, self.write_value_dim, bias=bias)
        elif mode == 'cross_attn_tf':
            # v6p5: full backbone decoder layer in cross-attention mode. Runs in
            # model_hidden_size, so write_value_dim must == hidden_size (enforced by
            # the wrapper). subtract_query=False: the layer output AT the M query rows
            # IS the written memory content.
            if self.write_value_dim != hidden_size:
                raise ValueError("cross_attn_tf write requires write_value_dim == hidden_size")
            self.block = CrossTransformerBlock(
                base_layer_cls=base_layer_cls, base_config=base_config,
                base_rotary=base_rotary, subtract_query=False)
        else:
            # v6p4 P1: multi-head (was single-head); same module as the read side.
            self.attn = LlamaCrossAttention(
                hidden_size=hidden_size, num_heads=num_heads,
                kv_hidden_size=hidden_size, out_hidden_size=self.write_value_dim, bias=bias)

    def _queries(self, B, queries):
        # None -> trainable bank (layer 0 / threading off); else threaded (B, M, d).
        return self.write_queries.unsqueeze(0).expand(B, -1, -1) if queries is None else queries

    def _pool(self, queries, tokens):
        k = self.k_proj(tokens)
        v = self.v_proj(tokens)
        attn = F.softmax(torch.matmul(queries, k.transpose(-1, -2)) * self.scaling, dim=-1)
        return torch.matmul(attn, v)

    def forward(self, hidden_states, queries=None):
        B = hidden_states.shape[0]
        q = self._queries(B, queries)
        if self.mode == 'pool':
            return self._pool(q, hidden_states)
        if self.mode == 'cross_attn_tf':
            # q = (B, M, d) memory-slot queries; kv = (B, T, d) post-attn tokens.
            return self.block(query=q, kv=hidden_states)
        return self.attn(from_states=q, to_states=hidden_states)

    def parallel(self, hidden_states, S, T, M, queries=None):
        B = hidden_states.shape[0]
        d = self.hidden_size
        q = (self.write_queries.view(1, 1, M, d).expand(B, S, M, d)
             if queries is None else queries.view(B, S, M, d))
        if self.mode == 'pool':
            out = self._pool(q, hidden_states.view(B, S, T, d))          # (B,S,M,wvd)
            return out.reshape(B, S * M, self.write_value_dim)
        if self.mode == 'cross_attn_tf':
            # block-diagonal over S: query (B,S*M,d), kv (B,S*T,d).
            return self.block.parallel(query=q.reshape(B, S * M, d),
                                       kv=hidden_states, S=S)
        # cross_attn block-diagonal: fold segments into batch (== S forward() calls).
        out = self.attn(from_states=q.reshape(B * S, M, d),
                        to_states=hidden_states.view(B, S, T, d).reshape(B * S, T, d))
        return out.view(B, S * M, self.write_value_dim)


class MemoryDecompress(nn.Module):
    """K memory vectors per segment -> T tokens per segment (residual content).

    forward(tokens, mem):              (B, T, d), (B, K, d_v) -> (B, T, d)
    parallel(tokens, mem, S, T, K):    (B, S*T, d), (B, S*K, d_v) -> (B, S*T, d)

    Same-segment read: tokens in segment s attend only to mem block s.
    Bit-equivalent between parallel and sequential. (In v6p0 the memory fed here
    is ``g`` — the R read-vector outputs of the GDN scan — so K == R.)
    """

    def __init__(self, hidden_size, write_value_dim, mode='cross_attn',
                 num_heads=1, bias=False,
                 base_layer_cls=None, base_config=None, base_rotary=None):
        super().__init__()
        if mode not in ('unpool', 'cross_attn', 'cross_attn_tf'):
            raise ValueError(f"mode must be 'unpool'|'cross_attn'|'cross_attn_tf', got '{mode}'")
        self.mode = mode
        self.hidden_size = hidden_size
        self.scaling = hidden_size ** -0.5
        if mode == 'unpool':
            self.k_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
            self.v_proj = nn.Linear(write_value_dim, hidden_size, bias=bias)
        elif mode == 'cross_attn_tf':
            # v6p5: full backbone decoder layer in cross-attention mode. The token
            # rows query the memory (g). subtract_query=True returns the residual
            # DELTA so the wrapper's out_h = post_attn + delta == a real decoder layer
            # over post_attn (the wrapper sets read_norm=Identity, so token_states IS
            # raw post_attn). Runs in hidden_size, so g must be in hidden_size
            # (write_value_dim == hidden_size, enforced by the wrapper).
            if write_value_dim != hidden_size:
                raise ValueError("cross_attn_tf read requires write_value_dim == hidden_size")
            self.block = CrossTransformerBlock(
                base_layer_cls=base_layer_cls, base_config=base_config,
                base_rotary=base_rotary, subtract_query=True)
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
        if self.mode == 'cross_attn_tf':
            # query = (B, T, d) tokens; kv = (B, K, d) memory g.
            return self.block(query=token_states, kv=memory_states)
        return self.cross_attn(from_states=token_states, to_states=memory_states)

    def parallel(self, token_states, mem, S, T, K):
        B = token_states.shape[0]
        d = self.hidden_size
        if self.mode == 'unpool':
            tokens = token_states.view(B, S, T, d)
            mem_v = mem.view(B, S, K, -1)
            k = self.k_proj(mem_v)
            v = self.v_proj(mem_v)
            attn = torch.matmul(tokens, k.transpose(-1, -2)) * self.scaling
            attn = F.softmax(attn, dim=-1)
            out = torch.matmul(attn, v)
            return out.reshape(B, S * T, d)
        if self.mode == 'cross_attn_tf':
            # block-diagonal over S: query (B,S*T,d), kv (B,S*K,d).
            return self.block.parallel(query=token_states, kv=mem, S=S)
        d_v = mem.shape[-1]
        from_states = token_states.view(B, S, T, d).reshape(B * S, T, d)
        to_states = mem.view(B, S, K, d_v).reshape(B * S, K, d_v)
        out = self.cross_attn(from_states=from_states, to_states=to_states)
        return out.view(B, S * T, d)


class RecurrentMemoryLayerWrapper(nn.Module):
    """Per-layer wrapper. Resolved formulas (single skip at the call site):

      identity:   out_h = post_attn + GDN(LN_f(post_attn))
      pool/xattn: out_h = post_attn + decompress(LN_r(post_attn), g)
                  where g = GDN_read_outputs over [read_queries, compress(post_attn)],
                  a fresh read of the pre-segment state S_{s-1}.
      id-read (write in {pool,cross_attn}, read='identity'):
                  out_h = post_attn + g[:T]
                  where g = GDN_read_outputs over [LN_r(post_attn) (T read-only),
                  LN_f(compress(post_attn)) (M writes)]. The tokens themselves are
                  the read-only valve positions (each reads S_{s-1} via its own GDN
                  query); there are no static read_queries and no decompress.

    ``fla_layer`` is a ReadAwareGatedDeltaNet with NO outer WithSkip wrapper.
    ``num_read_vectors`` (R) is a code-level option; it defaults to
    ``num_memory_vectors`` (M) and is intentionally NOT exposed as a config knob.
    """

    def __init__(self, base_layer, fla_layer, model_hidden_size,
                 num_memory_vectors=1, write_mode='cross_attn',
                 read_mode='cross_attn', write_value_dim=None,
                 num_compress_heads=1, num_read_vectors=None, gap_width=0,
                 thread_memory=False, layer_index=0, thread_state=None,
                 base_layer_cls=None, base_config=None, base_rotary=None):
        super().__init__()
        write_identity = (write_mode == 'identity')
        read_identity = (read_mode == 'identity')
        # v6p5: full-transformer cross-attention modes (a fresh backbone decoder layer
        # in cross-attention mode). Need the base layer class + config to build them.
        write_tf = (write_mode == 'cross_attn_tf')
        read_tf = (read_mode == 'cross_attn_tf')

        if write_mode not in ('pool', 'cross_attn', 'cross_attn_tf', 'identity'):
            raise ValueError(f"write_mode must be 'pool'|'cross_attn'|'cross_attn_tf'|'identity', got '{write_mode}'")
        if read_mode not in ('unpool', 'cross_attn', 'cross_attn_tf', 'identity'):
            raise ValueError(f"read_mode must be 'unpool'|'cross_attn'|'cross_attn_tf'|'identity', got '{read_mode}'")
        if write_identity and not read_identity:
            raise ValueError("write_mode='identity' requires read_mode='identity'")
        if (write_tf or read_tf) and (base_layer_cls is None or base_config is None):
            raise ValueError("cross_attn_tf modes need base_layer_cls/base_config "
                             "(threaded from RecurrentMemoryCell).")

        wvd = write_value_dim if write_value_dim is not None else model_hidden_size
        if write_identity and wvd != model_hidden_size:
            raise ValueError("identity mode requires write_value_dim == model_hidden_size")
        if read_identity and not write_identity and wvd != model_hidden_size:
            # state-pure identity read: the read tokens ARE post_attn (model_hidden_size),
            # fed straight into the GDN, so GDN must run in model_hidden_size dim.
            raise ValueError(
                "read_mode='identity' requires write_value_dim == model_hidden_size "
                "(GDN must run in model_hidden_size dim to accept post_attn directly)"
            )
        if (write_tf or read_tf) and wvd != model_hidden_size:
            # the backbone decoder layer runs in model_hidden_size, so the compressed
            # writes / read memory g must live in model_hidden_size too.
            raise ValueError("cross_attn_tf modes require write_value_dim == model_hidden_size")

        self.base_layer = base_layer
        self.fla_layer = fla_layer
        self.write_mode = write_mode
        self.read_mode = read_mode
        self.num_memory_vectors = num_memory_vectors
        self.num_read_vectors = num_read_vectors or num_memory_vectors  # R, defaults to M
        self.write_value_dim = wvd
        # G: zero, read-masked tokens inserted between reads and writes in the
        # identity-read GDN scan so the write conv can't reach the read tokens.
        self.gap_width = gap_width
        # v6p4 cross-layer threading: layer 0 uses the trainable banks; layers >0
        # reuse the previous layer's memory (write m_vecs / read g) as queries via
        # the shared `thread_state` dict owned by the cell.
        self.thread_memory = thread_memory
        self.layer_index = layer_index
        self.thread_state = thread_state
        if thread_memory and not write_identity and wvd != model_hidden_size:
            raise ValueError(
                "thread_memory requires write_value_dim == model_hidden_size "
                "(threaded write vectors are reused as next-layer compress queries)")

        self.fla_norm = nn.RMSNorm(wvd, eps=1e-5)
        # v6p5: for cross_attn_tf read, the decoder layer pre-norms internally and we
        # need out_h = post_attn + (layer_out - post_attn) == the full layer over RAW
        # post_attn, so the read-side norm must be the identity (token_states == post_attn).
        self.read_norm = nn.Identity() if read_tf else nn.RMSNorm(model_hidden_size, eps=1e-5)
        # base layer class/config/rotary for building cross_attn_tf blocks (v6p5).
        _tf_kw = dict(base_layer_cls=base_layer_cls, base_config=base_config,
                      base_rotary=base_rotary)

        if write_identity:
            # write=identity, read=identity (paired): bare GDN over the tokens.
            self.compress = None
            self.decompress = None
            self.read_queries = None
        elif read_identity:
            # write in {pool, cross_attn, cross_attn_tf}, read=identity: compress writes only.
            # The read tokens ARE post_attn (no static read_queries, no decompress);
            # they read S_{s-1} as read-only valve positions in the GDN scan.
            self.compress = MemoryCompress(
                hidden_size=model_hidden_size,
                num_vectors=num_memory_vectors,
                mode=write_mode,
                write_value_dim=wvd,
                num_heads=num_compress_heads,
                **_tf_kw,
            )
            self.decompress = None
            self.read_queries = None
        else:
            self.compress = MemoryCompress(
                hidden_size=model_hidden_size,
                num_vectors=num_memory_vectors,
                mode=write_mode,
                write_value_dim=wvd,
                num_heads=num_compress_heads,
                **_tf_kw,
            )
            self.decompress = MemoryDecompress(
                hidden_size=model_hidden_size,
                write_value_dim=wvd,
                mode=read_mode,
                num_heads=num_compress_heads,
                **_tf_kw,
            )
            # Dedicated static read queries, in memory (d_m) space. These ARE the
            # read tokens of the GDN scan; they read S_{s-1} and do not attend H.
            self.read_queries = nn.Parameter(torch.zeros(self.num_read_vectors, wvd))
            nn.init.normal_(self.read_queries, std=wvd ** -0.5)

        self.cache = Cache()
        self.parallel_mode = False
        self._p_S = self._p_T = self._p_M = 0
        self._p_attn_mask = None

        # Cache base_layer.forward positional-arg names so we can route *args
        # (e.g. GPT2's positional past_kv / cache_pos / attention_mask) to the
        # right keyword and override attention_mask without duplicates.
        try:
            sig = inspect.signature(self.base_layer.forward)
            self._base_param_names = [
                p for p in sig.parameters.keys() if p != 'self'
            ]
        except (TypeError, ValueError):
            self._base_param_names = ['hidden_states']

    def _call_base_layer(self, hidden_states, args, kwargs, attn_override=None):
        """Call self.base_layer with (hidden_states, *args, **kwargs), optionally
        overriding the attention_mask kwarg. *args are mapped to keywords based on
        the cached signature so models that pass args positionally (GPT2) don't
        clash with an attention_mask kwarg."""
        names = self._base_param_names
        pos_kwargs = dict(zip(names[1:1 + len(args)], args))
        merged = {**pos_kwargs, **kwargs}
        if attn_override is not None:
            merged['attention_mask'] = attn_override
        return self.base_layer(hidden_states, **merged)

    def reset_memory(self):
        # All cross-segment carry now lives in the GDN cache (recurrent_state +
        # conv_state); no separate prev_mem to reset.
        self.cache = Cache()

    def _gdn(self, x_norm, read_mask=None):
        out = self.fla_layer(
            x_norm,
            attention_mask=None,
            past_key_values=self.cache,
            use_cache=True,
            read_mask=read_mask,
        )
        self.cache = out[2]
        return out[0]

    @staticmethod
    def _build_read_mask(B, S, R, M, device):
        """(B, S*(R+M)) bool: True on the R read positions at the start of each
        segment, False on the M write positions."""
        one_seg = torch.cat([
            torch.ones(R, dtype=torch.bool, device=device),
            torch.zeros(M, dtype=torch.bool, device=device),
        ])
        mask = one_seg.repeat(S)
        return mask.unsqueeze(0).expand(B, -1)

    # --- v6p4 cross-layer threading helpers (no-ops when thread_memory is False) ---
    def _reset_thread(self):
        if self.thread_memory and self.layer_index == 0 and self.thread_state is not None:
            self.thread_state.clear()

    def _wq(self):
        if self.thread_memory and self.layer_index > 0 and self.thread_state is not None:
            return self.thread_state.get('w')
        return None

    def _store_w(self, m_vecs):
        if self.thread_memory and self.thread_state is not None:
            self.thread_state['w'] = m_vecs

    def _rq(self, default):
        if self.thread_memory and self.layer_index > 0 and self.thread_state is not None:
            r = self.thread_state.get('r')
            if r is not None:
                return r
        return default

    def _store_r(self, g):
        if self.thread_memory and self.thread_state is not None:
            self.thread_state['r'] = g

    def forward(self, hidden_states, *args, **kwargs):
        if self.parallel_mode:
            return self._forward_parallel(hidden_states, *args, **kwargs)
        return self._forward_recurrent(hidden_states, *args, **kwargs)

    def _forward_recurrent(self, hidden_states, *args, **kwargs):
        output = self._call_base_layer(hidden_states, args, kwargs)
        post_attn = output[0] if isinstance(output, tuple) else output
        self._reset_thread()

        if self.write_mode == 'identity':
            mem = self._gdn(self.fla_norm(post_attn))     # (B, T, d)
            out_h = post_attn + mem
        elif self.read_mode == 'identity':
            # State-pure identity read via the read-only valve: the T tokens
            # themselves are the read positions (beta=0, decay=1 -> they read
            # S_{s-1} without writing/decaying it); the M compressed writes
            # advance S_{s-1} -> S_s. One GDN scan over [reads(T), writes(M)],
            # no static read_queries, no decompress. read_norm normalizes the
            # read tokens, fla_norm the writes (kept separate, then concatenated).
            B, T = post_attn.shape[0], post_attn.shape[1]
            m_vecs = self.compress(post_attn, queries=self._wq())      # (B, M, d_m)
            self._store_w(m_vecs)
            M = m_vecs.shape[1]
            G = self.gap_width
            reads = self.read_norm(post_attn)                          # (B, T, d_m)
            writes = self.fla_norm(m_vecs)                             # (B, M, d_m)
            # [reads | gap(zeros) | writes]: the gap keeps read tokens out of the
            # write tokens' causal conv window so they can't leak into the state.
            gap = reads.new_zeros(B, G, reads.shape[-1])               # (B, G, d_m)
            gdn_in = torch.cat([reads, gap, writes], dim=1)            # (B, T+G+M, d_m)
            # read_mask True over reads AND gap (both valved: no write/decay).
            read_mask = self._build_read_mask(B, 1, T + G, M, post_attn.device)
            g_out = self._gdn(gdn_in, read_mask=read_mask)            # (B, T+G+M, d_m)
            r = g_out[:, :T]                                           # (B, T, d)
            out_h = post_attn + r
        else:
            B = post_attn.shape[0]
            d_m = self.write_value_dim
            R = self.num_read_vectors
            m_vecs = self.compress(post_attn, queries=self._wq())      # (B, M, d_m)
            self._store_w(m_vecs)
            M = m_vecs.shape[1]
            reads = self._rq(self.read_queries.unsqueeze(0).expand(B, R, d_m))  # (B, R, d_m)
            gdn_in = torch.cat([reads, m_vecs], dim=1)                 # (B, R+M, d_m)
            read_mask = self._build_read_mask(B, 1, R, M, post_attn.device)
            g_out = self._gdn(self.fla_norm(gdn_in), read_mask=read_mask)
            g = g_out[:, :R]                                           # (B, R, d_m)
            self._store_r(g)
            r = self.decompress(self.read_norm(post_attn), g)
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
        self._reset_thread()

        if self.write_mode == 'identity':
            # GDN over (B, S*T, d) — parallel scan is bit-equivalent to S
            # sequential calls of length T.
            mem = self._gdn(self.fla_norm(post_attn))
            out_h = post_attn + mem
        elif self.read_mode == 'identity':
            # Identity read, batched over S segments. Interleaved [reads(T),
            # writes(M)] per segment is contiguous and read_mask is per-position,
            # so the parallel GDN scan is bit-equivalent to S sequential
            # read+write pairs. r is the first T outputs of each segment.
            d_m = self.write_value_dim
            G = self.gap_width
            m_vecs = self.compress.parallel(post_attn, S, T, M, queries=self._wq())  # (B, S*M, d_m)
            self._store_w(m_vecs)
            m_vecs = m_vecs.view(B, S, M, d_m)
            reads = self.read_norm(post_attn).view(B, S, T, d_m)       # (B, S, T, d_m)
            writes = self.fla_norm(m_vecs)                             # (B, S, M, d_m)
            # per segment [reads | gap(zeros) | writes]; contiguous across S so
            # the parallel scan stays bit-equivalent to S recurrent calls.
            gap = reads.new_zeros(B, S, G, d_m)                        # (B, S, G, d_m)
            gdn_in = torch.cat([reads, gap, writes], dim=2)           # (B, S, T+G+M, d_m)
            gdn_in = gdn_in.reshape(B, S * (T + G + M), d_m)
            read_mask = self._build_read_mask(B, S, T + G, M, post_attn.device)
            g_out = self._gdn(gdn_in, read_mask=read_mask)            # (B, S*(T+G+M), d_m)
            g_out = g_out.view(B, S, T + G + M, d_m)
            r = g_out[:, :, :T, :].reshape(B, S * T, d_m)              # (B, S*T, d)
            out_h = post_attn + r
        else:
            d_m = self.write_value_dim
            R = self.num_read_vectors
            m_vecs = self.compress.parallel(post_attn, S, T, M, queries=self._wq())  # (B, S*M, d_m)
            self._store_w(m_vecs)
            m_vecs = m_vecs.view(B, S, M, d_m)
            reads = self._rq(self.read_queries.view(1, 1, R, d_m).expand(B, S, R, d_m))
            # interleaved per segment: [s0: R reads, M writes | s1: ...]
            gdn_in = torch.cat([reads, m_vecs], dim=2)                 # (B, S, R+M, d_m)
            gdn_in = gdn_in.reshape(B, S * (R + M), d_m)
            read_mask = self._build_read_mask(B, S, R, M, post_attn.device)
            g_out = self._gdn(self.fla_norm(gdn_in), read_mask=read_mask)
            g_out = g_out.view(B, S, R + M, d_m)
            g_seg = g_out[:, :, :R, :]                                 # (B, S, R, d_m)
            self._store_r(g_seg)
            g = g_seg.reshape(B, S * R, d_m)                           # (B, S*R, d_m)
            r = self.decompress.parallel(self.read_norm(post_attn), g, S, T, R)
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
        thread_memory=True,
        num_memory_vectors=1,
        write_value_dim=None,
        num_memory_heads=1,
        num_compress_heads=None,
        gap_width=None,
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
        self.thread_memory = thread_memory
        self.num_memory_vectors = num_memory_vectors
        self.write_value_dim = write_value_dim
        self.num_memory_heads = num_memory_heads
        # compress/decompress cross-attn heads, SEPARATE from the GDN heads (= num_heads).
        # None -> fall back to num_memory_heads (back-compat).
        self.num_compress_heads = (num_compress_heads if num_compress_heads is not None
                                   else num_memory_heads)
        # gap between reads and writes in identity-read; None -> conv_size+1.
        self.gap_width = gap_width
        self.max_n_segments = max_n_segments
        self.think_token_id = think_token_id
        self.answer_token_id = answer_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id

    def get(self, attr, default=None):
        return getattr(self, attr, default)

    def fla_layer_kwargs(self):
        # v6p3: only keys FLA's GatedDeltaNet.__init__ actually accepts. state_size is
        # encoded via head_dim (= state_size // num_heads, set by the runner); FLA has no
        # state_size / expand / conv_kernel params (those were silently dropped pre-v6p3).
        return {
            "num_heads": self.num_heads,
            "head_dim": self.head_dim,
            "expand_v": self.expand_v,
            "conv_size": self.conv_size,
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
                 num_memory_heads=1, num_compress_heads=None,
                 num_read_vectors=None, gap_width=None,
                 thread_memory=True,
                 **fla_layer_kwargs):
        super().__init__()
        self.model = base_model
        # v6p4: one dict shared by all layer wrappers; layer 0 clears it each forward,
        # each layer stashes its memory for the next layer to query from.
        self._thread_state = {}
        self.thread_memory = thread_memory

        # Gap between reads and writes (identity-read only). Default conv_size+1
        # so the write conv (looks back conv_size-1) can never reach a read token.
        conv_size = fla_layer_kwargs.get('conv_size',
                                         fla_layer_kwargs.get('conv_kernel', 4))
        eff_gap = gap_width if gap_width is not None else conv_size + 1

        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        identity = (write_mode == 'identity')
        # identity write OR identity read both feed model-dim vectors (the token
        # stream / the read tokens) straight into the GDN, so it must run in
        # model_hidden_size; only the disentangled read path uses write_value_dim.
        if identity or read_mode == 'identity':
            gdn_hidden_size = model_hidden_size
        else:
            gdn_hidden_size = write_value_dim or model_hidden_size
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        # Read-aware GDN subclass enables the read-only valve (beta=0, decay=1).
        # v6p3 FIX: ReadAwareGatedDeltaNet.__init__ is (self, *args, **kwargs), so
        # inspect.signature on IT matches nothing and silently dropped every GDN knob.
        # Filter against the REAL FLA class signature (the wrapper forwards **kwargs to
        # it) and HARD-ERROR on any requested knob FLA won't accept.
        layer_cls = ReadAwareGatedDeltaNet if fla_layer_name == "GatedDeltaNet" \
            else getattr(fla.layers, fla_layer_name)
        real_fla_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(real_fla_cls.__init__)
        excluded = {"self", "hidden_size", "layer_idx"}
        accepted = {p for p in sig.parameters if p not in excluded}
        dropped = {k for k in fla_layer_kwargs if k not in accepted}
        if dropped:
            raise ValueError(
                f"v6p3 GDN config safety-net: requested knob(s) {sorted(dropped)} are not "
                f"accepted by {real_fla_cls.__name__}.__init__ (accepted: {sorted(accepted)}). "
                f"Fix RecurrentMemoryConfig.fla_layer_kwargs() so nothing is silently dropped."
            )
        filtered_kwargs = {
            k: v for k, v in fla_layer_kwargs.items() if k not in excluded
        }

        transformer_layers = self._get_transformer_layers(base_model)
        # v6p5: handles for building cross_attn_tf full-transformer memory blocks
        # (a fresh layer of the SAME class as the backbone, built from base_config).
        base_layer_cls = type(transformer_layers[0])
        base_config = base_model.config
        _rope = 'position_embeddings' in inspect.signature(
            transformer_layers[0].forward).parameters
        base_rotary = getattr(getattr(base_model, 'model', None), 'rotary_emb', None) \
            if _rope else None
        for i, layer in enumerate(transformer_layers):
            fla_layer = layer_cls(
                hidden_size=gdn_hidden_size,
                layer_idx=0,
                **filtered_kwargs,
            ).to(dtype=model_dtype, device=model_device)
            # NOTE: no outer WithSkip wrapper. The single residual is at the call
            # site in RecurrentMemoryLayerWrapper.forward.

            wrapped = RecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer,
                model_hidden_size=model_hidden_size,
                num_memory_vectors=num_memory_vectors,
                write_mode=write_mode,
                read_mode=read_mode,
                write_value_dim=write_value_dim,
                num_compress_heads=(num_compress_heads if num_compress_heads is not None
                                    else num_memory_heads),
                num_read_vectors=num_read_vectors,
                gap_width=eff_gap,
                thread_memory=thread_memory,
                layer_index=i,
                thread_state=self._thread_state,
                base_layer_cls=base_layer_cls,
                base_config=base_config,
                base_rotary=base_rotary,
            )
            transformer_layers[i] = wrapped

        self._mask_cache = {}

        # v6p3: verify the GDN got the requested config (no silent fallback) and log
        # the resolved geometry once. Catches future signature/key-name regressions.
        _g0 = self._get_transformer_layers(self.model)[0].fla_layer
        _req_nh = fla_layer_kwargs.get("num_heads")
        _req_hd = fla_layer_kwargs.get("head_dim")
        if _req_nh is not None:
            assert _g0.num_heads == _req_nh, \
                f"GDN num_heads {_g0.num_heads} != requested {_req_nh}"
        if _req_hd is not None:
            assert _g0.head_k_dim == _req_hd, \
                f"GDN head_k_dim {_g0.head_k_dim} != requested {_req_hd}"
        print(f"[RMM v6p5] GDN resolved: num_heads={_g0.num_heads} "
              f"head_k_dim={_g0.head_k_dim} head_v_dim={_g0.head_v_dim} "
              f"state_numel/layer={_g0.num_heads * _g0.head_k_dim * _g0.head_v_dim} "
              f"(requested num_heads={_req_nh}, head_dim={_req_hd})", flush=True)

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

        Bit-equivalent (within kernel tolerance) to S sequential recurrent calls:
          - block-diag ATTN == per-segment ATTN
          - COMPRESS/DECOMPRESS.parallel are block-diagonal
          - GDN parallel scan over the contiguous interleaved [reads, writes]
            stream == S sequential GDN calls (read_mask applied per-position)
          - position_ids restarted per segment to match per-segment recurrent
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
    equivalent logits (verified by tests/test_rmm_v6p0_equivalence.py)."""

    def __init__(self, memory_cell, use_parallel_prefill=True, **rmt_kwargs):
        super().__init__()
        self.memory_cell = memory_cell
        self.use_parallel_prefill = use_parallel_prefill
        self.rmt_config = rmt_kwargs

    def forward(self, segments, labels, output_attentions=None,
                output_hidden_states=None, *args, **kwargs):
        if not segments:
            raise ValueError("requires at least one segment")

        # v6p5: only request base-model hidden states when the caller actually wants
        # them. Always-on output_hidden_states made transformers' check_model_inputs
        # recorder monkey-patch EVERY DecoderLayer in the module tree — including the
        # fresh layers inside cross_attn_tf blocks — leaking their (B*S, T+M, H)
        # internal sequences into hidden_states and breaking the concat. Logits/loss
        # never need hidden_states (runners never read them).
        want_hs = bool(output_hidden_states)

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
                output_hidden_states=want_hs,
            )
            cell_outputs.append(ctx_out)

            qt_out = self.memory_cell(
                input_ids=qt_seg["input_ids"],
                attention_mask=qt_seg.get("attention_mask"),
                output_hidden_states=want_hs,
            )
            cell_outputs.append(qt_out)
        else:
            for seg in segments:
                seg_out = self.memory_cell(
                    input_ids=seg["input_ids"],
                    attention_mask=seg.get("attention_mask"),
                    output_hidden_states=want_hs,
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
        # v6p5: build hidden states only when requested. Also filter to the token-stream
        # layers (batch B, seq == this cell-output's logit seq); cross_attn_tf's internal
        # decoder layers, if the recorder ever captures them, have a (B*S, T+M, H) shape
        # that must not be concatenated into the residual-stream hidden states.
        full_hidden_states = None
        if kwargs.get("output_hidden_states") and all(
            getattr(o, "hidden_states", None) is not None for o in cell_outputs
        ):
            def _token_stream(o):
                B, L = o.logits.shape[0], o.logits.shape[1]
                return tuple(h for h in o.hidden_states
                             if h.shape[0] == B and h.shape[1] == L)
            full_hidden_states = tuple(
                torch.cat(layer_hs, dim=1)
                for layer_hs in zip(*[_token_stream(o) for o in cell_outputs])
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
            num_compress_heads=getattr(config, 'num_compress_heads', None),
            gap_width=getattr(config, 'gap_width', None),
            thread_memory=getattr(config, 'thread_memory', True),
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
