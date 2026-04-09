# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMCA.
Advance N-level: N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Model file: modeling_rmt/huggingface_rmca_v3.py
- No parameter count explosion (justify any increase)
- Max experiment length: 50000 steps

## Current State
- N-level: 4
- Current best EM: -1.0 (starting fresh)
- Best variant: none
- Last updated: 2026-04-09

## Reference: Previous Work (N=2)
- **iter_108** achieved EM=0.9468 at N=2
- Used memory compression mechanism that selectively updates high-salience memory tokens
- All 10 human hyperparameter suggestions exhausted before architectural change
- Full results available in: `runs-autoresearch/n2/iter_108/`

## Current Understanding
Starting fresh at N=4. Previous N=2 results show that architectural changes (memory compression) can achieve near-perfect performance (0.9468 EM) after hyperparameter tuning is exhausted. The challenge is now scaling this to N=4, which requires the model to learn 4 associative pairs instead of 2.

Key question: Will the same memory compression mechanism scale to N=4, or will new architectural changes be needed?

---
