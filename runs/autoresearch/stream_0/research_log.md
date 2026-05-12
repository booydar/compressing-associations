# Research Log
Started: 2026-05-13 00:25

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n2/iter_000_baseline


## Iter 0 — baseline — EM: 0.8534 (N=2)
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**Wall time:** 56.5 min
**Result:** EM=0.8534 vs prev best=-1.0000
**Metric source:** all_results


## Iter 1 — RUNNING — N=2
**Hypothesis:** Increasing write_value_dim to 512 significantly boosts memory capacity for KV retrieval without violating state_size constraints.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n2/iter_001_write_value_dim_512_n2


## Iter 1 — kept — EM: 0.9122 (N=2)
**Hypothesis:** Increasing write_value_dim to 512 significantly boosts memory capacity for KV retrieval without violating state_size constraints.
**Wall time:** 57.0 min
**Result:** EM=0.9122 vs prev best=0.8534
**Metric source:** all_results
**Rationale:** Directions identify write_value_dim as the single biggest miss in v5p design and explicitly unlock it for sweeping up to 512.


