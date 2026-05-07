# Research Log
Started: 2026-05-07 11:48

## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline


## Iter 0 — FAILED — N=16
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 2 — RUNNING — N=16
**Hypothesis:** Decomposing the state vector into multiple parallel sub-states reduces interference and increases effective capacity without increasing total state_size.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_002_multi_head_state_split


## Iter 0 — baseline — EM: 0.0690 (N=16)
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**Wall time:** 120.0 min
**Result:** EM=0.0690 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline', '16', '25000']' timed out after 7199.999970371136 seconds


## Iter 1 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 2 — RUNNING — N=16
**Hypothesis:** Adding a learnable input gate to the FLA residual connection will allow the model to control how much recurrent memory signal flows through each layer.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_002_gated_fla_residual


## Iter 2 — kept — EM: 0.4828 (N=16)
**Hypothesis:** Adding a learnable input gate to the FLA residual connection will allow the model to control how much recurrent memory signal flows through each layer.
**Wall time:** 120.0 min
**Result:** EM=0.4828 vs prev best=0.0690
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_002_gated_fla_residual', '16', '25000']' timed out after 7199.999965849798 seconds
**Rationale:** The gap between token accuracy (0.4842) and EM (0.069) suggests the model struggles to consistently use its recurrent state. A learnable gate can modulate the FLA output before the residual addition, enabling the model to learn when to rely on memory vs. direct transformer processing.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Adding a learned output projection after the FLA layer will allow the model to transform the recurrent memory signal into a representation better suited for the residual stream.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_003_fla_output_projection


## Iter 3 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_003_fla_output_projection
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=16
**Hypothesis:** Adding layer normalization before the learnable gate will stabilize the recurrent memory signal and improve gradient flow through the residual connection.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_004_norm_before_gate


## Iter 4 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_004_norm_before_gate
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 5 — RUNNING — N=16
**Hypothesis:** Adding a learnable bias initialization to the FLA gate will enable better warm-start of recurrent memory dynamics.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_005_fla_gate_bias_init


## Iter 5 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_005_fla_gate_bias_init
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 6 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_006_fix_broken_base


## Iter 6 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_006_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 7 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_007_fix_broken_base


## Iter 7 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_007_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 8 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_008_fix_broken_base


## Iter 8 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_008_fix_broken_base
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 9 — RUNNING — N=16
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_009_fix_broken_base


## Iter 9 — kept — EM: 0.7708 (N=16)
**Hypothesis:** Fix broken base: experiment error: Experiment script exited with code 1
**Wall time:** 120.0 min
**Result:** EM=0.7708 vs prev best=0.4828
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_009_fix_broken_base', '16', '25000']' timed out after 7199.999970690114 seconds
**Rationale:** The committed HEAD crashes at runtime with the same error on every iteration. Fix the root cause before any other change.


