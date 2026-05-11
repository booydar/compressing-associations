# Experiment Summary

## Iter 0 | failed | N=16
- Hypothesis: [Stream 1] baseline — RMM v5 default stack
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_000_baseline

## Iter 1 | failed | N=16
- Hypothesis: Enforcing float32 accumulation in GDN state updates preserves memory precision at state_size=32.
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Direction 4 identifies precision as a bottleneck; higher internal precision mitigates quantization loss without violating state_size constraints.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_001_gdn_fp32_accumulation

## Iter 2 | failed | N=16
- Hypothesis: Splitting the state into parallel subspaces within GDN increases effective capacity without increasing state_size parameter.
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Direction 4 requires architectural equivalents for capacity; parallel subspaces allow more information storage within the 32 limit.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_002_gdn_parallel_state_subspaces

## Iter 3 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_1/modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_003_fix_broken_base

## Iter 4 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_1/modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_004_fix_broken_base

## Iter 5 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_1/modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_005_fix_broken_base

## Iter 6 | failed | N=16
- Hypothesis: Fix broken base: experiment error: Experiment script exited with code 1
- Target: runs/autoresearch/stream_1/modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_006_fix_broken_base

## Iter 7 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: runs/autoresearch/stream_1/modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.
- exp_path: 

## Iter 8 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_008/executor_prompt.txt']' timed out after 900 seconds
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_008/executor_prompt.txt']' timed out after 900 seconds
- Rationale: Direction 5 explicitly requests alternatives to GatedDeltaNet; Linear Attention offers different capacity/precision tradeoffs.
- exp_path: 

## Iter 9 | failed | N=16
- Hypothesis: Switching from Mamba2 to SLA (Sliding Linear Attention) improves short-range recall for KV retrieval.
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Mamba2's state-space design optimizes long-range modeling but may underperform on short-range exact recall tasks. SLA's sliding window mechanism better preserves recent key-value associations within the strict state_size=32 constraint.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_009_sla_replace_mamba2

## Iter 10 | failed | N=16
- Hypothesis: FAILED: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_010/planner_prompt.txt']' timed out after 900 seconds
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_010/planner_prompt.txt']' timed out after 900 seconds
- Rationale: (none)
- exp_path: 

## Iter 11 | failed | N=16
- Hypothesis: Increasing num_memory_vectors from 1 to 4 provides more memory capacity for storing key-value associations without changing state_size.
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: The current configuration uses only 1 memory vector, which may be insufficient for storing 2 key-value pairs. Increasing to 4 vectors provides a 4x expansion in memory capacity while staying within the state_size=32 constraint.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_011_increase_memory_vectors_to_4

## Iter 12 | failed | N=16
- Hypothesis: Removing the broken dual-state mechanism and orthogonal rotation simplifies the model to a clean baseline for debugging.
- Target: modeling_rmt/huggingface_rmm_v5.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: All 12 previous iterations failed with exit code 1 due to an indentation bug in huggingface_rmm_v5.py. After fixing the syntax error, the model runs but includes experimental features (dual-state mechanism, orthogonal rotation) that may introduce bugs. Removing these untested features will establish a clean baseline.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_012_remove_broken_features_baseline

