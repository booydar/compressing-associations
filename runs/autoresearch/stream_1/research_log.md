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


