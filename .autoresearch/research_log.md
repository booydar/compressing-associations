# Research Log## Iter 0 — RUNNING — N=8
**Hypothesis:** baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations/runs-autoresearch/n8/iter_000_baseline


## Iter 0 — baseline — EM: 0.1276 (N=8)
**Hypothesis:** baseline — exact copy of v2
**Wall time:** 39.3 min
**Result:** EM=0.1276 vs prev best=-1.0000
**Metric source:** all_results


## Iter 1 — RUNNING — N=8
**Hypothesis:** RMCA-Hybrid will improve EM accuracy by combining delta rule updates with gating mechanisms for more stable memory writing.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.2/runs-autoresearch/n8/iter_001


## Iter 1 — reverted — EM: 0.0318 (N=8)
**Hypothesis:** RMCA-Hybrid will improve EM accuracy by combining delta rule updates with gating mechanisms for more stable memory writing.
**Wall time:** 29.6 min
**Result:** EM=0.0318 vs prev best=0.1276
**Metric source:** all_results
**Rationale:** Implementing human_directions item #19 (RMCA-Hybrid). This is a pending suggestion from the priority list that must be addressed before hyperparameter tuning. The hybrid architecture combines delta rule memory updates with gating for better gradient flow and memory stability during associative retrieval.


