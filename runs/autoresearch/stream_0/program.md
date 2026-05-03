# Research Program (Stream 0)

## Objective
Maximize exact-match (EM) on associative retrieval task.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Target files: modeling_rmt/huggingface_rmm_v2.py (architecture) or .autoresearch/experiment_config.yaml (hyperparameters)
- No parameter count explosion (~50% max increase without strong justification)
- Max experiment length: 25000 steps

## Allowed Changes
- **Architecture**: Any modification to huggingface_rmm_v2.py (layers, memory mechanisms, etc.)
- **Model hyperparameters**: n_layer, n_head, n_embd and model-specific params (in experiment_config.yaml)
- **Training hyperparameters**: lr, batch_size, warmup_steps, eval_steps, logging_steps, early_stopping_patience (in experiment_config.yaml)

## Current State
- Stream: 0
- N-level: 16
- Current best EM: 0.0010
- Best variant: iter_249
- Last updated: 2026-05-03 21:32

## Current Understanding
(updated each iteration by autoresearch loop)
