
## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline


## Iter 0 — FAILED — N=16
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=16
**Hypothesis:** Increase n_head from 4 to 8 to improve multi-association tracking capacity while keeping state_size constant at 32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_001_increase_n_head_to_8


## Iter 1 — RUNNING — N=16
**Hypothesis:** Increase expand_v from 4.0 to 6.0 to give the FLA layer more capacity to store associative mappings
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_2/n16/iter_001_expand_v_six


## Iter 1 — RUNNING — N=16
**Hypothesis:** Reduce n_head from 4 to 2 to increase head_dim from 8 to 16 while keeping state_size constant at 32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_001_reduce_n_head_to_2


## Iter 0 — baseline — EM: 0.2006 (N=16)
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**Wall time:** 120.0 min
**Result:** EM=0.2006 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline', '16', '25000']' timed out after 7199.99997029081 seconds


