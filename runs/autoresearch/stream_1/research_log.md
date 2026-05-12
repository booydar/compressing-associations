# Research Log
Started: 2026-05-13 00:26

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 1] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline


## Iter 0 — FAILED — N=2
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=2
**Hypothesis:** Increasing write_value_dim to 256 will significantly improve EM by expanding write capacity without violating state_size <= 32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_001_write_val_dim_256_n2


## Iter 1 — kept — EM: 0.4924 (N=2)
**Hypothesis:** Increasing write_value_dim to 256 will significantly improve EM by expanding write capacity without violating state_size <= 32.
**Wall time:** 56.2 min
**Result:** EM=0.4924 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** Directions identify write_value_dim as the single biggest miss in v5p design and it is currently an unlocked capacity knob.


## Iter 2 — RUNNING — N=2
**Hypothesis:** Setting num_memory_vectors to 4 with cross_attn write_mode will maximize write throughput for pool-1tps regime.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_002_mem_vecs_4_cross_n2


## Iter 2 — kept — EM: 0.9922 (N=2)
**Hypothesis:** Setting num_memory_vectors to 4 with cross_attn write_mode will maximize write throughput for pool-1tps regime.
**Wall time:** 50.1 min
**Result:** EM=0.9922 vs prev best=0.4924
**Metric source:** all_results
**Rationale:** M>1 is the only way to multiply write throughput when tokens_per_segment=1 and cross_attn is required for M>1 to work.


## >>> N-level advanced to N=4 <<<
Previous N achieved EM=0.9922 >= threshold 0.95.


