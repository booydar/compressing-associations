# Research Log
Started: 2026-05-13 23:10

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 2] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n2/iter_000_baseline


## Iter 0 — baseline — EM: 0.9918 (N=2)
**Hypothesis:** [Stream 2] baseline — RMM v5 default stack
**Wall time:** 34.7 min
**Result:** EM=0.9918 vs prev best=-1.0000
**Metric source:** all_results


## >>> N-level advanced to N=4 <<<
Previous N achieved EM=0.9918 >= threshold 0.95.


## Iter 1 — RUNNING — N=4
**Hypothesis:** Increasing write_value_dim to 256 will expand the effective memory capacity per write vector without violating the state_size constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_001_wvdim_256_sweep


## Iter 1 — kept — EM: 0.1872 (N=4)
**Hypothesis:** Increasing write_value_dim to 256 will expand the effective memory capacity per write vector without violating the state_size constraint.
**Wall time:** 71.3 min
**Result:** EM=0.1872 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** The directions explicitly flag write_value_dim as the primary intended capacity knob and current biggest miss. Scaling it tests the throughput vs. capacity trade-off in the pool-1tps regime.


## Iter 2 — RUNNING — N=4
**Hypothesis:** Setting num_memory_vectors to 4 and switching write_mode to cross_attn will multiply write throughput per segment while maintaining parallel-prefill compatibility.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_002_memvec_4_crosswrite


## Iter 2 — reverted — EM: 0.1522 (N=4)
**Hypothesis:** Setting num_memory_vectors to 4 and switching write_mode to cross_attn will multiply write throughput per segment while maintaining parallel-prefill compatibility.
**Wall time:** 71.2 min
**Result:** EM=0.1522 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** With tokens_per_segment locked at 1, increasing M is the only viable path to scale write capacity. cross_attn is required to structurally support M>1 writes.


