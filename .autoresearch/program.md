# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMCA.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Model file: modeling_rmt/huggingface_rmca_v3.py
- No parameter count explosion (justify any increase)
- Max experiment length: 50000 steps

## Current State
- N-level: 2
- Current best EM: 0.9468
- Best variant: iter_108
- Last updated: 2026-04-08 15:12

## Current Understanding
After iter 108 achieved EM=0.9468 with a memory compression mechanism, the model demonstrates that architectural changes can significantly improve performance after hyperparameter tuning exhausted (all 10 human directions tried). The memory compression approach that selectively updates high-salience memory tokens proved effective at N=2. Next steps: either refine this mechanism further or attempt to advance to N=4.

---
