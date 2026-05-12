# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMM v5 with GatedDeltaNet (GDN) and the v5 memory path.
Target: EM ≥ 0.99 at N=16.

## Constraints
- Target files: modeling_rmt/huggingface_rmm_v5.py (architecture) or .autoresearch/experiment_config.yaml (unlocked hyperparameters only)
- No parameter count explosion (~50% max increase without strong justification)
- Max experiment length: 25000 steps
- Hard-frozen parameters: align with `.autoresearch/experiment_config.yaml` (e.g. n_layer=4, n_embd≤128, batch_size=64, state_size≤32); trainer: `run_rmm_on_kv_retrieval-v5.py`

## Allowed Changes
- **Architecture**: Any modification to modeling_rmt/huggingface_rmm_v5.py (GDN layer internals, gating, attention, memory read/write paths)
- **Unlocked hyperparameters**: early_stopping_patience, eval_steps, logging_steps only

## Current State
- N-level: 16
- Current best EM: 0.0 (fresh start — baseline not yet run)
- Best variant: none yet

## Current Understanding
- expand_v=4.0 is critical: in prior runs this single change took EM from 0.02 → 0.36
- warmup_steps=10000 improves training stability vs 5000
- conv_kernel=2 (vs 4) improves memory precision
- state_size=64 achieved EM=0.87 in a prior run but violates the hard constraint (must stay ≤32)
- The bottleneck is GDN capacity within the state_size=32 constraint
- Architectural ideas worth exploring: multi-head improvements, gating mechanisms inside GDN, better key/value projection, auxiliary memory channels
