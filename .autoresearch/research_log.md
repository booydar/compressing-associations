## Iter 0 — RUNNING — N=8
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n8/iter_000_baseline


## Iter 0 — FAILED — N=8
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n8/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n8/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n8/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=8
**Hypothesis:** Increasing n_embd from 64 to 128 will provide more representational capacity for the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_1/n8/iter_001_n_embd_128_capacity


## Iter 0 — baseline — EM: 0.1350 (N=8)
**Hypothesis:** [Stream 0] baseline — exact copy of v2
**Wall time:** 100.7 min
**Result:** EM=0.1350 vs prev best=-1.0000
**Metric source:** all_results


## Iter 1 — kept — EM: 0.9728 (N=8)
**Hypothesis:** Increasing n_embd from 64 to 128 will provide more representational capacity for the associative retrieval task.
**Wall time:** 98.3 min
**Result:** EM=0.9728 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** The current n_embd=64 may be too small for the model to effectively store and retrieve key-value associations. Since state_size and n_layer are already at their maximums, increasing the embedding dimension is a natural next step. This is a hyperparameter change following the HYPERPARAMETER-FIRST rule.


## >>> N-level advanced to N=16 <<<
Previous N achieved EM=0.9728 >= threshold 0.95.


