# Plan: split identity-read GDN into separate read-only / write-only ops (v6p0)

File: `modeling_rmt/huggingface_rmm_v6p0.py`

## Status / open question (READ FIRST)
We have NOT confirmed there is an actual leak. Earlier "conv bridges read/write
boundary" diagnosis was **wrong**: the QT (target/last) segment reads only
`S_{S-1}` through the recurrent bottleneck, and its own writes go to `S_S` which
is never read. The conv only enriches how *context* writes land in the shared
state — not an answer bypass. So id-pool's high scores may simply be a stronger
**reader** (content-dependent token query) vs pool/unpool's static query.

Decide BEFORE implementing — two cheap checks:
1. Pull step-0 eval EM from the run's `trainer_state.json` (`eval_on_start=True`).
   High at step 0 (random init) => real data/eval leak. ~chance => genuine.
2. On the box: zero the per-layer cache right before the QT (or corrupt the
   queried pair's value in the context). EM collapses => genuine retrieval, no
   leak, this split is UNNECESSARY for correctness. EM stays high => real bypass
   in the read path; hunt that instead (this split won't be the fix).

If both say "genuine / no leak", this split is optional (cleaner code only),
not a bug fix. Treat the rest of this plan as the agreed design IF we proceed.

## Design (agreed)
Per layer, per segment, faithful to the scheme but the single
`[reads, writes]` GDN scan is split into two GDN calls so nothing convolves
across the read/write boundary:

```
H      = BaseLayer(x)
reads, writes = build(H)          # mode-specific
g      = self._gdn_read(reads)    # READ-only: gated readout of S_{s-1}, state untouched
         self._gdn_write(writes)  # WRITE-only: S_{s-1} -> S_s
r      = combine(H, g)            # identity: r = g ; disentangled: r = Decompress(H, g)
out    = H + r
```

### Why two calls (not the one-scan)
FLA `Cache` is mutated **in place**; `out[2] is self.cache`. A read run on
`self.cache` overwrites its `conv_state` with the read tokens (recurrent_state
is preserved by the valve beta=0/decay=1, but conv_state is not). In one
contiguous scan the writes sit in the reads' causal conv shadow, so the conv
pulls raw read tokens into the write k/v. Separating the calls + giving the read
its own throwaway state container keeps the write's conv clean.

## New helpers on `RecurrentMemoryLayerWrapper`

```python
def _read_state_cache(self):
    """Throwaway Cache seeded with a clone of the current recurrent_state
    (S_{s-1}). `.clone()` (NOT detach().clone()) keeps the autograd graph so
    grads from the read flow back through S_{s-1} into prior writes. conv_state
    starts empty -> read convolves only within its own segment (cross-segment
    info reaches the read ONLY via S_{s-1}). Discarded; self.cache untouched."""
    fork = Cache()
    try:
        state = self.cache[0]
    except (KeyError, IndexError, TypeError):
        return fork                       # empty -> read sees zero state (S_{-1})
    if not state:
        return fork
    get = state.get if hasattr(state, 'get') else (lambda k, d=None: state[k] if k in state else d)
    rec = get('recurrent_state')
    fork.update(
        recurrent_state=rec.clone() if rec is not None else None,  # clone keeps grad graph
        conv_state=None,                  # fresh conv -> no cross-segment conv channel
        layer_idx=0,
        offset=0,
    )
    return fork

def _gdn_read(self, reads):
    """Read-only: gated readout of S_{s-1} (beta=0/decay=1). Persistent cache untouched."""
    B, L = reads.shape[0], reads.shape[1]
    read_mask = reads.new_ones(B, L, dtype=torch.bool)
    out = self.fla_layer(reads, attention_mask=None,
                         past_key_values=self._read_state_cache(),
                         use_cache=True, read_mask=read_mask)
    return out[0]

def _gdn_write(self, writes):
    """Write-only: S_{s-1} -> S_s on the persistent cache. No read_mask -> normal writes."""
    out = self.fla_layer(writes, attention_mask=None,
                         past_key_values=self.cache, use_cache=True)
    self.cache = out[2]
    return out[0]
```

Keep existing `_gdn` as-is for identity-WRITE (paired) and the disentangled
branch (see scope).

## Rewire — identity-read branches ONLY

Recurrent (replaces current `l.435-444`):
```python
B, T = post_attn.shape[0], post_attn.shape[1]
m_vecs = self.compress(post_attn)        # (B, M, d)
reads  = self.read_norm(post_attn)       # (B, T, d)
writes = self.fla_norm(m_vecs)           # (B, M, d)
g = self._gdn_read(reads)                # read S_{s-1}  (T outputs)
self._gdn_write(writes)                  # advance S_{s-1} -> S_s
out_h = post_attn + g
```

Parallel (replaces current `l.483-494`) — per-segment loop; base-attn +
`compress.parallel` stay parallel:
```python
d = self.write_value_dim
m_vecs = self.compress.parallel(post_attn, S, T, M).view(B, S, M, d)
reads  = self.read_norm(post_attn).view(B, S, T, d)
writes = self.fla_norm(m_vecs)           # (B, S, M, d)
g_chunks = []
for s in range(S):
    g_chunks.append(self._gdn_read(reads[:, s].contiguous()))
    self._gdn_write(writes[:, s].contiguous())
g = torch.cat(g_chunks, dim=1)           # (B, S*T, d)
out_h = post_attn + g
```
Now parallel and recurrent run the same two ops in the same order =>
equivalence is trivial; writes' GDN scan never contains a read token.

## Scope decisions
1. Touch ONLY identity-read branches. Leave the disentangled pool/unpool branch
   on its single `[static_reads, writes]` scan — it's the known-good, leak-free
   baseline; splitting it would shift its conv numerics and force re-verification.
   (Revisit only if we want full uniformity.)
2. `conv_state=None` for the read. Risk: FLA may dislike recurrent_state present
   + conv_state None + offset 0. If it errors on the box, fallback = a zeros
   conv_state of the right shape instead of None.
3. Accept 2x GDN calls per segment (overhead ignored for now).

## Verification (on the box, `~/envs/fla/bin/python`)
- `tests/test_rmm_v6p0_equivalence.py` — parallel == recurrent (esp. pool/identity).
- `tests/test_rmm_v6p0_readonly.py` — valve invariants.
- NEW regression to add: write-state must be invariant to the read tokens'
  content (run a segment's write with the segment's real reads vs random reads;
  resulting recurrent_state must be identical). This pins the fix.

## Context
- v5p6 used `_fork_cache` (full deep clone) + separate read/write calls. User
  dislikes the heavy clone; v5p7 is the preferred good baseline. This plan keeps
  only a single-tensor (`recurrent_state`) grad-preserving clone, fresh conv.
- Remote `2h100-airi` (192.168.15.10) was timing out (VPN down) — could edit the
  sshfs mount but not run tests. Run tests next session once reachable.
