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


