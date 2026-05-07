# Experiment Summary

## Iter 0 | failed | N=16
- Hypothesis: [Stream 0] baseline — exact copy of v2
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline

## Iter 1 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: Multiplicative dynamics often preserve signal integrity better than additive updates in low-dimensional recurrent states.
- exp_path: 

## Iter 1 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Rationale: LRU architectures utilize diagonal state matrices that can capture different time scales more efficiently than standard delta networks.
- exp_path: 

## Iter 3 | failed | N=16
- Hypothesis: Adding a learned output projection after the FLA layer will allow the model to transform the recurrent memory signal into a representation better suited for the residual stream.
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The token accuracy (0.7108) exceeds EM (0.4828), indicating inconsistent memory utilization. A learned projection can map the FLA output space to the residual stream space more effectively than direct addition, enabling better integration of recurrent memory signals.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_003_fla_output_projection

## Iter 4 | failed | N=16
- Hypothesis: Adding layer normalization before the learnable gate will stabilize the recurrent memory signal and improve gradient flow through the residual connection.
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The current gated residual connection applies the gate directly to the FLA output without normalization. LayerNorm before gating is a standard technique in modern architectures (e.g., GPT-3, Llama) that stabilizes training by normalizing the signal being gated, which should improve convergence and final EM accuracy.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_004_norm_before_gate

## Iter 5 | failed | N=16
- Hypothesis: Adding a learnable bias initialization to the FLA gate will enable better warm-start of recurrent memory dynamics.
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The gap between token accuracy (0.7108) and EM (0.4828) suggests inconsistent memory utilization across segments. The current gated residual lacks explicit bias control for the FLA gate initialization, which can lead to poor recurrent state learning early in training. A learnable bias allows the model to start with more favorable memory dynamics.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_005_fla_gate_bias_init

## Iter 6 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_0/modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_006_fix_broken_base

## Iter 7 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_0/modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_007_fix_broken_base

## Iter 8 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_0/modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_008_fix_broken_base

## Iter 10 | failed | N=16
- Hypothesis: FAILED: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Rationale: (none)
- exp_path: 

## Iter 12 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Rationale: The memory capacity bottleneck in GDN can be addressed by adding a separate low-rank memory pathway that complements the existing recurrent state, effectively doubling usable capacity within the constraint.
- exp_path: 

