## Iter 0 — RUNNING — N=8
**Hypothesis:** baseline — exact copy of v2
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_000_baseline


## Iter 0 — baseline — EM: 0.0002 (N=8)
**Hypothesis:** baseline — exact copy of v2
**Wall time:** 18.4 min
**Result:** EM=0.0002 vs prev best=-1.0000
**Metric source:** all_results


## Iter 0 — FAILED — N=8
**Error:** unhandled: cannot access local variable 'planner_trace' where it is not associated with a value
**Recovery status:** not_attempted


## Iter 1 — RUNNING — N=8
**Hypothesis:** Adding deep supervision losses at intermediate layers will provide stronger gradient signals to early layers and improve exact-match accuracy on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_001


## Iter 1 — kept — EM: 0.0006 (N=8)
**Hypothesis:** Adding deep supervision losses at intermediate layers will provide stronger gradient signals to early layers and improve exact-match accuracy on the associative retrieval task.
**Wall time:** 17.4 min
**Result:** EM=0.0006 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** Deep supervision (#15) is a pending human direction. The current config sets use_deep_supervision=true and deep_supervision_weight=0.1, but deep_supervision_layers is not specified in experiment_config.yaml, which may mean supervision is not being applied to specific intermediate layers. This is a hyperparameter-adjacent architectural flag that needs proper configuration.


## Iter 1 — FAILED — N=8
**Error:** unhandled: git add failed: The following paths are ignored by one of your .gitignore files:
.autoresearch/artifacts
Use -f if you really want to add them.
**Recovery status:** not_attempted


## Iter 2 — RUNNING — N=8
**Hypothesis:** Adding memory dropout will regularize the memory tokens and prevent overfitting to specific memory patterns, improving generalization on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_002


## Iter 2 — FAILED — N=8
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_002
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 3 — RUNNING — N=8
**Hypothesis:** Adding memory dropout will regularize memory tokens and prevent overfitting to specific memory patterns, improving generalization on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_003


## Iter 3 — reverted — EM: 0.0004 (N=8)
**Hypothesis:** Adding memory dropout will regularize memory tokens and prevent overfitting to specific memory patterns, improving generalization on the associative retrieval task.
**Wall time:** 20.1 min
**Result:** EM=0.0004 vs prev best=0.0006
**Metric source:** all_results
**Rationale:** Implementing human_directions item #14 (Memory dropout). Previous experiments with deep supervision (item #15, Done) and gradient clipping (item #16, Done) have been completed. Memory dropout is a pending hyperparameter/architectural hybrid that adds regularization specifically to memory tokens. The previous iteration 2 failed due to experiment script errors, not the concept itself.


## Iter 3 — FAILED — N=8
**Error:** unhandled: git add failed: The following paths are ignored by one of your .gitignore files:
.autoresearch/artifacts
Use -f if you really want to add them.
**Recovery status:** not_attempted


## Iter 4 — RUNNING — N=8
**Hypothesis:** Adding memory dropout will regularize the memory tokens and prevent overfitting to specific memory patterns, improving generalization on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.3/runs-autoresearch/n8/iter_004


## Iter 4 — reverted — EM: 0.0004 (N=8)
**Hypothesis:** Adding memory dropout will regularize the memory tokens and prevent overfitting to specific memory patterns, improving generalization on the associative retrieval task.
**Wall time:** 30.5 min
**Result:** EM=0.0004 vs prev best=0.0006
**Metric source:** all_results
**Rationale:** Implementing human directions item #14 (Memory dropout). This is a pending hyperparameter/architectural hybrid change that adds regularization to memory tokens. Previous deep supervision and gradient clipping have been tried, but memory-specific regularization has not yet been explored.


