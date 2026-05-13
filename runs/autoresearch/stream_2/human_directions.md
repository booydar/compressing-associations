# Human directions — v5p1 (parallel-prefill RMM, pool-1tps regime)

## Mission
Maximize EM on the KV associative-retrieval task using `modeling_rmt/huggingface_rmm_v5p1.py` + `run_rmm_on_kv_retrieval-v5p1.py`. The pool-1tps regime means each context segment is **1 token** processed in parallel via block-diag attn; the GDN scan runs over `S*M` write vectors; the qt segment is recurrent. Push the architecture HARD — do not be timid.

## Hard locks (proposing changes = automatic failure)
1. `state_size <= 32` (GDN recurrent state width). This is the headline constraint of the paper.
2. `n_layer = 4`, `n_embd = 128`, `n_head = 4`, `batch_size = 64`, `warmup_steps = 10000`.
3. `tokens_per_segment = 1` (pool-1tps regime — do not change).
4. `fla_layer = GatedDeltaNet` for the main sweep. May be swapped only as a labeled baseline experiment, not as a path to improve EM.
5. `max_steps <= 25000`.

## UNLOCKED — go wild here
1. **`write_value_dim`** — GDN hidden width. This is the intended capacity knob. Sweep {128, 192, 256, 384, 512}. NOT bounded by state_size.
2. **`num_memory_vectors` (M)** — write vectors per segment. {1, 2, 4, 8}. With tps=1 this is the only way to multiply write throughput.
3. **`write_mode`** — `pool` ↔ `cross_attn`. `cross_attn` adds q_proj+out_proj and is required to make M>1 work; verify.
4. **`read_mode`** — `unpool` ↔ `cross_attn` with `num_memory_heads ∈ {1,2,4}`.
5. **`write_residual`** — try `true`. Adds a second read using current-segment (un-shifted) mem; free extra path.
6. **`expand_v`, `conv_kernel`** — sweep {1.0, 2.0, 4.0} and {2, 4} respectively.
7. **`learning_rate`** — {5e-5, 1e-4, 3e-4}.
8. **Architecture edits to `huggingface_rmm_v5p1.py`** — encouraged. In particular:
   - Multi-stream GDN: two parallel GDN paths of state_size=16 concatenated (total ≤32 preserved).
   - Layer-order experiments (READ→ATTN→WRITE vs current WRITE→GDN→READ→ATTN) in the parallel path.
   - Per-layer independent vs shared writers/readers.
   - Re-introduce a smarter `OrthogonalRotation` (currently off): full state-mixing matrix instead of last-dim only.
   - Move qt segment through parallel-prefill too (drop the recurrent fallback).

## N-progression
Start at **N=2** (must clear EM ≥ 0.95 before climbing), then **N=4**, then **N=8**. Failure mode of prior runs was launching at N=16 with EM ≈ 0 — the meta-loop had no signal. Stay in a regime where the model actually learns.

## Discipline
- Bold > safe. Capacity-killing micro-tweaks (norm placements, decay variants) without a capacity argument will be rejected.
- One concrete architectural hypothesis per iter. Justify in terms of effective state capacity or write-throughput, not "stabilization".
- Keep an eye on the unused `write_value_dim` axis — this is currently the single biggest miss in the v5p design.
