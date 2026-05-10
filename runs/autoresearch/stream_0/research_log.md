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


