# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMCA.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Target files: modeling_rmt/huggingface_rmca_v3.py (architecture) or .autoresearch/experiment_config.yaml (hyperparameters)
- No parameter count explosion (~50% max increase without strong justification)
- Max experiment length: 25000 steps

## Allowed Changes
- **Architecture**: Any modification to huggingface_rmca_v3.py (layers, attention, memory mechanisms, etc.)
- **Model hyperparameters**: n_layer, n_head, n_embd, n_mem_tokens (in experiment_config.yaml)
- **Training hyperparameters**: lr, batch_size, warmup_steps, eval_steps, logging_steps, early_stopping_patience (in experiment_config.yaml)

## Current State
- N-level: 8
- Current best EM: 0.0012
- Best variant: iter_018
- Last updated: 2026-04-17 08:47

## Current Understanding
(updated each iteration by autoresearch loop)
