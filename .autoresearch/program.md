# Research Program — v5p1

## Objective
Maximize EM on KV associative retrieval using RMM **v5p1** (parallel-prefill, ortho rotation off) in the pool-1tps regime. Climb N: N=2 → N=4 → N=8 as EM ≥ 0.95 at each level.

## Target files
- Architecture: `modeling_rmt/huggingface_rmm_v5p1.py`
- Trainer: `run_rmm_on_kv_retrieval-v5p1.py`
- Hyperparameters: `.autoresearch/experiment_config.yaml`

## Constraints (hard)
- `state_size ≤ 32`, `n_layer = 4`, `n_embd = 128`, `n_head = 4`, `batch_size = 64`, `warmup_steps = 10000`, `tokens_per_segment = 1`, `max_steps ≤ 25000`.
- Parameter count: ≤ 50% increase without strong justification.

## Unlocked levers (push hard here)
- `write_value_dim` (GDN hidden width — NOT bound to state_size; main capacity knob).
- `num_memory_vectors` (M), `write_mode`, `read_mode`, `num_memory_heads`, `write_residual`.
- `expand_v`, `conv_kernel`, `learning_rate`.
- Any architecture edit to `huggingface_rmm_v5p1.py`: multi-stream GDN, layer-order surgery, full-matrix orthogonal rotation, drop the recurrent qt fallback.

## Current state
- N-level: 2
- Current best EM: 0.0 (fresh)
- Best variant: none yet

## Current Understanding
- Manual v5p1 with M=1, pool/unpool, lr=3e-4 at N=2 was already climbing (EM 0→0.015 by step 1500/200k). The base is healthy.
- The pool-1tps regime turns the model into "per-token write into GDN with M slots and a learnable extractor." The two biggest underused axes are `write_value_dim` and `M`.
- See `knowledge/RESEARCH_DIRECTION.md` for paper-level framing — capacity bottleneck is the headline claim; this stream supplies the validation numbers.
