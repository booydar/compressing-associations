## Iter 0 — RUNNING — N=16
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_0/n16/iter_000_baseline


## Iter 0 — FAILED — N=16
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_0/n16/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_0/n16/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=16
**Hypothesis:** Increase FLA layer from 1 to 4 heads to improve capacity for tracking multiple key-value associations
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_1/n16/iter_001_n4_heads_baseline


## Iter 0 — baseline — EM: 0.0162 (N=16)
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**Wall time:** 120.0 min
**Result:** EM=0.0162 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v3/runs/autoresearch/stream_0/n16/iter_000_baseline', '16', '25000']' timed out after 7199.999974830076 seconds


