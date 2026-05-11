# Experiment Summary

## Iter 2 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: Multi-head processing allows parallel tracking of different memory patterns. This effectively multiplies capacity without increasing total state dimension.
- exp_path: 

## Iter 3 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: Low-precision arithmetic during state decay and accumulation can degrade memory quality. fp32 accumulation preserves gradients and state fidelity.
- exp_path: 

## Iter 8 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: S4 achieved the best EM (0.0032) so far. Mamba2 extends S4 with input-dependent selection patterns that allow the model to dynamically focus on relevant memory, potentially improving associative retrieval accuracy within the state_size=32 constraint.
- exp_path: 

## Iter 15 | reverted | N=16
- Hypothesis: Implementing low-rank state factorization in GDN will increase effective memory capacity without exceeding state_size=32 constraint
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: 0.0006
- Success: Change ran successfully and produced a measurable result.
- Weaknesses: It did not improve over the previous best.
- Failures: No executor or run failure, but the hypothesis underperformed.
- Rationale: Factorizing the state into lower-dimensional components allows storing more information per state dimension through multiplicative interactions, addressing the memory capacity bottleneck
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_015_low_rank_state_factorization

