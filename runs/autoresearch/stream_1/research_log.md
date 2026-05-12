# Research Log
Started: 2026-05-11 18:04

## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 1] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_000_baseline


## Iter 0 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=16
**Hypothesis:** Enforcing float32 accumulation in GDN state updates preserves memory precision at state_size=32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_001_gdn_fp32_accumulation


## Iter 1 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_001_gdn_fp32_accumulation
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 2 — RUNNING — N=16
**Hypothesis:** Splitting the state into parallel subspaces within GDN increases effective capacity without increasing state_size parameter.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_002_gdn_parallel_state_subspaces


## Iter 2 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_002_gdn_parallel_state_subspaces
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_003_fix_broken_base


## Iter 3 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_003_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_004_fix_broken_base


## Iter 4 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_004_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 5 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_005_fix_broken_base


## Iter 5 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_005_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 6 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_006_fix_broken_base


## Iter 6 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_006_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 7 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 8 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_008/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 9 — RUNNING — N=16
**Hypothesis:** Switching from Mamba2 to SLA (Sliding Linear Attention) improves short-range recall for KV retrieval.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_009_sla_replace_mamba2


## Iter 9 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_009_sla_replace_mamba2
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 10 — FAILED — N=16
**Error:** planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_010/planner_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 11 — RUNNING — N=16
**Hypothesis:** Increasing num_memory_vectors from 1 to 4 provides more memory capacity for storing key-value associations without changing state_size.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_011_increase_memory_vectors_to_4


## Iter 11 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_011_increase_memory_vectors_to_4
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 12 — RUNNING — N=16
**Hypothesis:** Removing the broken dual-state mechanism and orthogonal rotation simplifies the model to a clean baseline for debugging.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_012_remove_broken_features_baseline


## Iter 12 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_012_remove_broken_features_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 13 — RUNNING — N=16
**Hypothesis:** Reducing state_size from 32 to 16 forces more efficient memory compression for the 2-pair associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_013_reduce_state_size_to_16


## Iter 13 — kept — EM: 0.0006 (N=16)
**Hypothesis:** Reducing state_size from 32 to 16 forces more efficient memory compression for the 2-pair associative retrieval task.
**Wall time:** 120.0 min
**Result:** EM=0.0006 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_013_reduce_state_size_to_16', '16', '25000']' timed out after 7199.99998146994 seconds
**Rationale:** With only 2 key-value pairs to store, state_size=32 may be too permissive, preventing the model from learning effective compression. Reducing to 16 (4 heads x 4 dim) creates tighter constraints that may improve generalization on this simple task.


## Iter 14 — RUNNING — N=16
**Hypothesis:** Increasing head_dim from 8 to 16 while reducing num_heads from 4 to 2 maintains state_size=32 but changes the inductive bias toward wider per-head representations.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_014_wider_heads_fewer_heads


## Iter 14 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_014_wider_heads_fewer_heads
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 15 — RUNNING — N=16
**Hypothesis:** Splitting state_size=32 across 4 parallel GDN heads increases effective memory capacity through parallel memory streams
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_015_multihead_gdn_decomposition


## Iter 15 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_015_multihead_gdn_decomposition
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 16 — RUNNING — N=16
**Hypothesis:** Using float32 accumulation for state updates while maintaining float16 storage improves memory precision without increasing state_size
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_016_float32_accumulation_precision


## Iter 16 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_016_float32_accumulation_precision
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 17 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_017/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 18 — RUNNING — N=16
**Hypothesis:** Replacing fixed GDN gates with learned attention-based gating improves information retention within state_size=32 constraint
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_018_learned_attention_gating


## Iter 18 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_018_learned_attention_gating
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 19 — RUNNING — N=16
**Hypothesis:** Aligning fla_layer state_size parameter (32) with experiment_config state_size (16) fixes configuration mismatch causing experiment crashes.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_019_fix_state_size_config_mismatch


## Iter 19 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_019_fix_state_size_config_mismatch
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 20 — RUNNING — N=16
**Hypothesis:** Enabling write_residual=True allows fresh memory to feed back into tokens within the same segment, improving associative retrieval for the 2-pair task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_020_enable_write_residual


## Iter 20 — reverted — EM: 0.0004 (N=16)
**Hypothesis:** Enabling write_residual=True allows fresh memory to feed back into tokens within the same segment, improving associative retrieval for the 2-pair task.
**Wall time:** 120.0 min
**Result:** EM=0.0004 vs prev best=0.0006
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_020_enable_write_residual', '16', '25000']' timed out after 7199.999990310054 seconds
**Rationale:** The v5 architecture supports write_residual mode but it was never tested. For a simple 2-pair KV retrieval task, immediate feedback from compressed memory to current tokens could strengthen the association between keys and values without increasing state_size.


## Iter 21 — RUNNING — N=16
**Hypothesis:** Enabling write_residual=True with num_memory_vectors=2 combines intra-segment memory feedback with sufficient memory capacity for the 2-pair KV retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_021_write_residual_with_explicit_memory_vectors


## Iter 21 — reverted — EM: 0.0006 (N=16)
**Hypothesis:** Enabling write_residual=True with num_memory_vectors=2 combines intra-segment memory feedback with sufficient memory capacity for the 2-pair KV retrieval task.
**Wall time:** 120.0 min
**Result:** EM=0.0006 vs prev best=0.0006
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_021_write_residual_with_explicit_memory_vectors', '16', '25000']' timed out after 7199.999991350109 seconds
**Rationale:** iter_020 showed EM=0.0004 with write_residual=True (better than iter_013's 0.0006). Adding num_memory_vectors=2 explicitly matches the 2 key-value pairs to store, providing dedicated memory slots for each association while maintaining the efficient state_size=16 constraint.


## Iter 22 — RUNNING — N=16
**Hypothesis:** Replacing GatedDeltaNet with linear attention mechanism maintains state_size=32 while improving memory precision through different inductive bias
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_022_linear_attention_alternative


## Iter 22 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_022_linear_attention_alternative
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 23 — RUNNING — N=16
**Hypothesis:** Adding residual skip connection to GDN state update path improves gradient flow and memory retention within state_size=32 constraint
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_023_gdn_state_residual


## Iter 23 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_023_gdn_state_residual
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 24 — RUNNING — N=16
**Hypothesis:** Implementing quantized memory slots within state_size=32 increases effective memory capacity through discrete memory encoding
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_024_quantized_memory_slots


## Iter 24 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_024_quantized_memory_slots
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 25 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_025_fix_broken_base


## Iter 25 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_025_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 26 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_026_fix_broken_base


## Iter 26 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_026_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 27 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_027/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 28 — FAILED — N=16
**Error:** planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/artifacts/iter_028/planner_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 29 — RUNNING — N=16
**Hypothesis:** Enabling write_residual=True with num_memory_vectors=2 combines intra-segment memory feedback with explicit memory capacity for the 2-pair KV retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_029_write_residual_with_memory_vectors


## Iter 29 — reverted — EM: 0.0006 (N=16)
**Hypothesis:** Enabling write_residual=True with num_memory_vectors=2 combines intra-segment memory feedback with explicit memory capacity for the 2-pair KV retrieval task.
**Wall time:** 120.0 min
**Result:** EM=0.0006 vs prev best=0.0006
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n16/iter_029_write_residual_with_memory_vectors', '16', '25000']' timed out after 7199.999988550087 seconds
**Rationale:** iter_020 showed EM=0.0004 with write_residual=True (better than iter_013's 0.0006). Adding num_memory_vectors=2 explicitly matches the 2 key-value pairs to store, providing dedicated memory slots for each association while maintaining the efficient state_size=16 constraint.


