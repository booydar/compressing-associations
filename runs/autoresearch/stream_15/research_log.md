# Research Log
Started: 2026-05-07 12:21

## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 15] baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_000_baseline


## Iter 0 — baseline — EM: 0.7868 (N=16)
**Hypothesis:** [Stream 15] baseline — exact copy of v2
**Wall time:** 120.0 min
**Result:** EM=0.7868 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_000_baseline', '16', '25000']' timed out after 7199.999973851023 seconds


## Iter 1 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/artifacts/iter_001/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 2 — RUNNING — N=16
**Hypothesis:** Using float32 precision for internal memory state updates will reduce quantization error and improve effective capacity without changing state_size.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_002_fp32_state_accumulation


## Iter 2 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_002_fp32_state_accumulation
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 3 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 4 — RUNNING — N=16
**Hypothesis:** Adding a learned skip connection around the FLA layer will allow the model to preserve information flow when recurrent compression is detrimental.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_004_gated_fla_residual


## Iter 4 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_004_gated_fla_residual
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 5 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 6 — RUNNING — N=16
**Hypothesis:** Adding a small learnable additive bias to the decay output will prevent complete memory forgetting and improve retrieval on long sequences.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_006_decay_bias_memory_retention


## Iter 6 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_006_decay_bias_memory_retention
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 7 — RUNNING — N=16
**Hypothesis:** Reducing expand_v from 6.0 to 4.0 will stabilize training and improve memory compression for the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_007_reduced_expand_v_stability


## Iter 7 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_007_reduced_expand_v_stability
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 8 — RUNNING — N=16
**Hypothesis:** Adding an input gate to control memory write intensity will improve key-value binding precision within state_size=32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_008_input_gate_memory_write


## Iter 8 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_008_input_gate_memory_write
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 9 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/artifacts/iter_009/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 10 — RUNNING — N=16
**Hypothesis:** Reducing learning_rate from 2e-4 to 1e-4 will stabilize training and allow better convergence on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_010_reduced_lr_stable_training


## Iter 10 — reverted — EM: 0.0600 (N=16)
**Hypothesis:** Reducing learning_rate from 2e-4 to 1e-4 will stabilize training and allow better convergence on the associative retrieval task.
**Wall time:** 120.0 min
**Result:** EM=0.0600 vs prev best=0.7868
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_15/n16/iter_010_reduced_lr_stable_training', '16', '25000']' timed out after 7199.999965860974 seconds
**Rationale:** The baseline achieved EM=0.7868 but many architectural experiments failed with executor errors. A conservative learning rate reduction is a low-risk hyperparameter change that may improve optimization stability without requiring architectural modifications.


