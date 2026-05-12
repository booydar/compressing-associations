# Research Log
Started: 2026-05-10 18:42

## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_000_baseline


## Iter 0 — baseline — EM: 0.0004 (N=16)
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**Wall time:** 51.2 min
**Result:** EM=0.0004 vs prev best=-1.0000
**Metric source:** all_results


## Iter 1 — RUNNING — N=16
**Hypothesis:** Replacing the GatedDeltaNet layer with standard Linear Attention will improve memory precision within the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_001_replace_gdn_with_linear_attn


## Iter 1 — kept — EM: 0.0006 (N=16)
**Hypothesis:** Replacing the GatedDeltaNet layer with standard Linear Attention will improve memory precision within the state_size=32 constraint.
**Wall time:** 107.1 min
**Result:** EM=0.0006 vs prev best=0.0004
**Metric source:** all_results
**Rationale:** GatedDeltaNet may suffer from precision loss during state updates. Linear Attention uses kernel approximations that might preserve information better at lower state capacities.


## Iter 2 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 3 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 4 — RUNNING — N=16
**Hypothesis:** Increasing expand_v from 2.0 to 4.0 will improve memory capacity by expanding the value projection dimension in GDN.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_004_increase_expand_v_to_4


## Iter 4 — reverted — EM: 0.0002 (N=16)
**Hypothesis:** Increasing expand_v from 2.0 to 4.0 will improve memory capacity by expanding the value projection dimension in GDN.
**Wall time:** 61.2 min
**Result:** EM=0.0002 vs prev best=0.0006
**Metric source:** all_results
**Rationale:** With state_size constrained to 32, the value projection bottleneck limits information flow. Increasing expand_v doubles the intermediate value dimension, allowing richer state representations without violating the state_size constraint.


## Iter 5 — RUNNING — N=16
**Hypothesis:** Adding layer normalization to GDN state update computations will improve memory precision at state_size=32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_005_gdn_layer_norm


## Iter 5 — reverted — EM: 0.0006 (N=16)
**Hypothesis:** Adding layer normalization to GDN state update computations will improve memory precision at state_size=32
**Wall time:** 63.2 min
**Result:** EM=0.0006 vs prev best=0.0006
**Metric source:** all_results
**Rationale:** Direction 4 identifies precision loss in GDN layer as bottleneck; normalization can stabilize state representations without increasing state_size


## Iter 6 — RUNNING — N=16
**Hypothesis:** Residual connections around GDN layer will preserve information flow and improve memory retention within state_size=32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_006_gdn_residual_connection


## Iter 6 — kept — EM: 0.0024 (N=16)
**Hypothesis:** Residual connections around GDN layer will preserve information flow and improve memory retention within state_size=32
**Wall time:** 104.3 min
**Result:** EM=0.0024 vs prev best=0.0006
**Metric source:** all_results
**Rationale:** Architecture change to improve capacity without violating state_size constraint; different from failed head-splitting approach in iter 2


## Iter 7 — RUNNING — N=16
**Hypothesis:** Replacing GatedDeltaNet with S4-style state space model will achieve higher memory capacity within state_size=32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_007_gdn_s4_alternative


## Iter 7 — kept — EM: 0.0032 (N=16)
**Hypothesis:** Replacing GatedDeltaNet with S4-style state space model will achieve higher memory capacity within state_size=32
**Wall time:** 104.9 min
**Result:** EM=0.0032 vs prev best=0.0024
**Metric source:** all_results
**Rationale:** Direction 5 explicitly requests exploring alternatives to GDN; S4 offers different memory mechanisms than Linear Attention (iter 1)


## Iter 8 — FAILED — N=16
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 9 — RUNNING — N=16
**Hypothesis:** Increasing num_memory_vectors from 1 to 4 will provide more compressed memory slots for storing segment-level representations, improving associative retrieval without violating the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_009_increase_memory_vectors_to_4


## Iter 9 — reverted — EM: 0.0022 (N=16)
**Hypothesis:** Increasing num_memory_vectors from 1 to 4 will provide more compressed memory slots for storing segment-level representations, improving associative retrieval without violating the state_size=32 constraint.
**Wall time:** 120.0 min
**Result:** EM=0.0022 vs prev best=0.0032
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_009_increase_memory_vectors_to_4', '16', '25000']' timed out after 7199.999991389923 seconds
**Rationale:** S4 achieved the best EM (0.0032) with num_memory_vectors=1. Increasing the number of memory vectors provides more capacity to store compressed segment representations through the MemoryWriter/MemoryReader mechanism, which is orthogonal to the FLA state_size constraint.


## Iter 10 — RUNNING — N=16
**Hypothesis:** Adding learnable decay rates per state dimension in GDN will improve memory retention without increasing state_size beyond 32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_010_learnable_decay_per_dim


## Iter 10 — reverted — EM: 0.0030 (N=16)
**Hypothesis:** Adding learnable decay rates per state dimension in GDN will improve memory retention without increasing state_size beyond 32.
**Wall time:** 104.9 min
**Result:** EM=0.0030 vs prev best=0.0032
**Metric source:** all_results
**Rationale:** Fixed decay may limit capacity utilization; learnable decay allows the model to adaptively control memory retention per dimension within the state_size constraint.


## Iter 11 — RUNNING — N=16
**Hypothesis:** Implementing a hybrid GDN + lightweight attention mechanism will improve memory precision by combining state-space efficiency with attention-based retrieval.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_011_gdn_hybrid_attention


## Iter 11 — reverted — EM: 0.0024 (N=16)
**Hypothesis:** Implementing a hybrid GDN + lightweight attention mechanism will improve memory precision by combining state-space efficiency with attention-based retrieval.
**Wall time:** 116.0 min
**Result:** EM=0.0024 vs prev best=0.0032
**Metric source:** all_results
**Rationale:** Pure SSM approaches (iter 7, 8) failed; combining GDN with a small attention head (e.g., 4 heads, 16 dim each) may provide better capacity utilization within state_size=32.


## Iter 12 — RUNNING — N=16
**Hypothesis:** Adding orthogonal state rotation before GDN update will improve memory precision by decorrelating state dimensions within the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_012_orthogonal_state_rotation


## Iter 12 — kept — EM: 0.0034 (N=16)
**Hypothesis:** Adding orthogonal state rotation before GDN update will improve memory precision by decorrelating state dimensions within the state_size=32 constraint.
**Wall time:** 120.0 min
**Result:** EM=0.0034 vs prev best=0.0032
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_012_orthogonal_state_rotation', '16', '25000']' timed out after 7199.9999901200645 seconds
**Rationale:** State dimension correlation may waste capacity; orthogonal rotation can spread information more evenly across state dimensions without violating the hard state_size limit.


## Iter 13 — RUNNING — N=16
**Hypothesis:** Adding a learnable gate to control orthogonal rotation strength will allow adaptive state transformation based on input context.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_013_gated_orthogonal_rotation


## Iter 13 — reverted — EM: 0.0026 (N=16)
**Hypothesis:** Adding a learnable gate to control orthogonal rotation strength will allow adaptive state transformation based on input context.
**Wall time:** 120.0 min
**Result:** EM=0.0026 vs prev best=0.0034
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_013_gated_orthogonal_rotation', '16', '25000']' timed out after 7199.999983880902 seconds
**Rationale:** The orthogonal rotation in iter_012 improved EM to 0.0034 by decorrelating state dimensions. Adding a scalar gate (initialized near 0) allows the model to learn when rotation helps vs. when identity pass-through is better, providing adaptive control without increasing state_size.


## Iter 14 — RUNNING — N=16
**Hypothesis:** Adding per-head orthogonal rotation will improve memory precision by allowing independent decorrelation patterns for each state dimension head within the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_014_per_head_orthogonal_rotation


## Iter 14 — reverted — EM: 0.0034 (N=16)
**Hypothesis:** Adding per-head orthogonal rotation will improve memory precision by allowing independent decorrelation patterns for each state dimension head within the state_size=32 constraint.
**Wall time:** 120.0 min
**Result:** EM=0.0034 vs prev best=0.0034
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_014_per_head_orthogonal_rotation', '16', '25000']' timed out after 7199.999985249946 seconds
**Rationale:** The global orthogonal rotation (iter_012) achieved the best EM (0.0034) by decorrelating state dimensions. However, a single 32x32 rotation may be suboptimal for capturing head-specific correlation patterns. With n_head=4 and head_dim=8 (state_size=32), applying separate 8x8 orthogonal rotations per head allows more flexible decorrelation while maintaining the same total state capacity.


## Iter 15 — RUNNING — N=16
**Hypothesis:** Implementing low-rank state factorization in GDN will increase effective memory capacity without exceeding state_size=32 constraint
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_015_low_rank_state_factorization


## Iter 15 — reverted — EM: 0.0006 (N=16)
**Hypothesis:** Implementing low-rank state factorization in GDN will increase effective memory capacity without exceeding state_size=32 constraint
**Wall time:** 73.9 min
**Result:** EM=0.0006 vs prev best=0.0034
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.


## Iter 16 — RUNNING — N=16
**Hypothesis:** Implementing dual-path state update with fast and slow temporal pathways will improve memory retention across different time scales
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_016_dual_path_state_temporal


## Iter 16 — kept — EM: 0.0036 (N=16)
**Hypothesis:** Implementing dual-path state update with fast and slow temporal pathways will improve memory retention across different time scales
**Wall time:** 120.0 min
**Result:** EM=0.0036 vs prev best=0.0034
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_016_dual_path_state_temporal', '16', '25000']' timed out after 7199.999975760002 seconds
**Rationale:** Separating state updates into fast (short-term) and slow (long-term) pathways allows the model to maintain both immediate context and persistent memory within the same state_size budget


## Iter 17 — RUNNING — N=16
**Hypothesis:** Adding content-adaptive decay modulation to the dual-state mechanism will improve memory retention by dynamically adjusting decay rates based on input significance.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_017_adaptive_decay_modulation


## Iter 17 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_017_adaptive_decay_modulation
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 18 — FAILED — N=16
**Error:** executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Apply the change described in the attached instructions file exactly. Do not ask questions.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/artifacts/iter_018/executor_prompt.txt']' timed out after 900 seconds
**Recovery status:** not_attempted


## Iter 19 — RUNNING — N=16
**Hypothesis:** Implementing mixed-precision state storage with higher precision for critical dimensions will improve memory precision within the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_019_mixed_precision_state


## Iter 19 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_019_mixed_precision_state
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 20 — RUNNING — N=16
**Hypothesis:** Adding a gated memory write mechanism that controls when information enters the state will improve retention by reducing interference from irrelevant inputs.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_020_gated_memory_write


## Iter 20 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_020_gated_memory_write
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 21 — RUNNING — N=16
**Hypothesis:** Adding a multiplicative interaction between fast and slow states will improve memory capacity by enabling non-linear state combinations within the state_size=32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_021_dual_state_multiplicative_interaction


## Iter 21 — reverted — EM: 0.0022 (N=16)
**Hypothesis:** Adding a multiplicative interaction between fast and slow states will improve memory capacity by enabling non-linear state combinations within the state_size=32 constraint.
**Wall time:** 120.0 min
**Result:** EM=0.0022 vs prev best=0.0036
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_021_dual_state_multiplicative_interaction', '16', '25000']' timed out after 7199.999989409931 seconds
**Rationale:** The dual-state mechanism (iter_016, EM=0.0036) uses a linear weighted combination of fast and slow states. A multiplicative interaction (element-wise product followed by projection) can capture higher-order correlations between timescales without increasing state_size, providing richer memory representations.


## Iter 22 — RUNNING — N=16
**Hypothesis:** Adding a residual connection from the original GDN output to the dual-state combined output will improve memory precision by preserving the base GDN computation while benefiting from multi-timescale state tracking.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_022_dual_state_residual_gdn


## Iter 22 — reverted — EM: 0.0032 (N=16)
**Hypothesis:** Adding a residual connection from the original GDN output to the dual-state combined output will improve memory precision by preserving the base GDN computation while benefiting from multi-timescale state tracking.
**Wall time:** 120.0 min
**Result:** EM=0.0032 vs prev best=0.0036
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_022_dual_state_residual_gdn', '16', '25000']' timed out after 7199.99998882995 seconds
**Rationale:** The dual-state mechanism (iter_016, EM=0.0036) combines fast and slow states through a learned gate, but this linear combination may discard useful information from the original GDN state update. Adding a residual connection ensures the base GDN computation is preserved, similar to how iter_006's residual connection improved EM from 0.0006 to 0.0024.


## Iter 23 — RUNNING — N=16
**Hypothesis:** Adding sinusoidal temporal modulation to dual-state decay rates will enable the model to learn oscillatory memory patterns that improve associative retrieval within state_size=32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_023_sinusoidal_temporal_decay


## Iter 23 — reverted — EM: 0.0034 (N=16)
**Hypothesis:** Adding sinusoidal temporal modulation to dual-state decay rates will enable the model to learn oscillatory memory patterns that improve associative retrieval within state_size=32.
**Wall time:** 120.0 min
**Result:** EM=0.0034 vs prev best=0.0036
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_023_sinusoidal_temporal_decay', '16', '25000']' timed out after 7199.999987410149 seconds
**Rationale:** The dual-state mechanism (iter_016, EM=0.0036) uses fixed learned decay parameters. Sinusoidal modulation inspired by positional encodings allows the model to capture periodic temporal patterns in memory decay, providing a richer inductive bias for associative retrieval without increasing state complexity or causing the failures seen in iter_17/19/20.


## Iter 24 — RUNNING — N=16
**Hypothesis:** Replacing GatedDeltaNet with S4-style diagonal state space model will improve memory precision and capacity within state_size=32 constraint through better gradient flow and selective retention
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_024_s4_alternative_gdn


## Iter 24 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_024_s4_alternative_gdn
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 25 — RUNNING — N=16
**Hypothesis:** Implementing linear attention with compression mechanism as GDN alternative will reduce memory interference while maintaining retrieval precision within state_size=32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_025_linear_attention_compression


## Iter 25 — reverted — EM: 0.0032 (N=16)
**Hypothesis:** Implementing linear attention with compression mechanism as GDN alternative will reduce memory interference while maintaining retrieval precision within state_size=32
**Wall time:** 120.0 min
**Result:** EM=0.0032 vs prev best=0.0036
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n16/iter_025_linear_attention_compression', '16', '25000']' timed out after 7199.999986950075 seconds
**Rationale:** Linear attention with compression provides a fundamentally different memory architecture than GDN, avoiding the bottlenecks in GDN's gating mechanism while respecting the state_size constraint.


