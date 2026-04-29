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


## Iter 0 — RECOVERED — N=8
**Recovered from:** all_results
**Recovered EM:** 0.1350


## Iter 1 — RUNNING — N=8
**Hypothesis:** Increasing n_embd from 64 to 128 will provide more representational capacity for the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n8/iter_001_n_embd_128_capacity


## Iter 2 — RUNNING — N=16
**Hypothesis:** Increasing learning_rate from 1e-3 to 5e-3 will accelerate convergence and improve final EM accuracy.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_1/n16/iter_002_lr_5e_3_convergence


## Iter 1 — kept — EM: 0.9770 (N=8)
**Hypothesis:** Increasing n_embd from 64 to 128 will provide more representational capacity for the associative retrieval task.
**Wall time:** 100.2 min
**Result:** EM=0.9770 vs prev best=0.1350
**Metric source:** all_results
**Rationale:** Stream 1 achieved EM=0.9728 with n_embd=128 on N=8, while stream 0 baseline with n_embd=64 only reached EM=0.135. Since n_layer, state_size, and conv_kernel are already at their maximums, increasing n_embd is the most direct hyperparameter improvement following the HYPERPARAMETER-FIRST rule.


## >>> N-level advanced to N=16 <<<
Previous N achieved EM=0.9770 >= threshold 0.95.


## Iter 2 — RUNNING — N=16
**Hypothesis:** Increasing learning_rate from 1e-3 to 0.01 will improve convergence speed and final EM accuracy on N=16.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n16/iter_002_lr_0_01_convergence


## Iter 2 — kept — EM: 0.0010 (N=16)
**Hypothesis:** Increasing learning_rate from 1e-3 to 5e-3 will accelerate convergence and improve final EM accuracy.
**Wall time:** 120.0 min
**Result:** EM=0.0010 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_1/n16/iter_002_lr_5e_3_convergence', '16', '25000']' timed out after 7199.9999791199225 seconds
**Rationale:** With n_embd=128 achieving 0.9728 EM, the model has sufficient capacity but may benefit from a higher learning rate to reach optimal convergence. Since structural hyperparameters (n_layer, state_size, n_embd) are at their maximums, tuning learning_rate is the logical next step per HYPERPARAMETER-FIRST.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Increasing n_head from 2 to 4 will improve FLA attention capacity for parallel key-value association tracking.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_1/n16/iter_003_n_head_4_parallel_capacity


## Iter 2 — kept — EM: 0.0004 (N=16)
**Hypothesis:** Increasing learning_rate from 1e-3 to 0.01 will improve convergence speed and final EM accuracy on N=16.
**Wall time:** 101.6 min
**Result:** EM=0.0004 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** With n_embd=128 achieving EM=0.977 on N=8, the model has sufficient capacity. Stream 1 is testing lr=5e-3 on N=16. Testing a higher learning rate (0.01) could further accelerate convergence. Following HYPERPARAMETER-FIRST, learning_rate tuning is appropriate before architectural changes.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Increasing n_head from 2 to 4 will improve parallel capacity for tracking multiple key-value associations on N=16.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_0/n16/iter_003_n_head_4_parallel_capacity


## Iter 3 — reverted — EM: 0.0006 (N=16)
**Hypothesis:** Increasing n_head from 2 to 4 will improve FLA attention capacity for parallel key-value association tracking.
**Wall time:** 120.0 min
**Result:** EM=0.0006 vs prev best=0.0010
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v2/runs/autoresearch/stream_1/n16/iter_003_n_head_4_parallel_capacity', '16', '25000']' timed out after 7199.999970679986 seconds
**Rationale:** With n_embd=128 achieving EM=0.97+ on N=8, the model has sufficient embedding capacity. Current n_head=2 is relatively low for the state_size=32 budget (can support 4 heads with head_dim=8). Increasing n_head allows the GatedDeltaNet to track multiple associations in parallel, which is critical for the KV retrieval task. This follows HYPERPARAMETER-FIRST as it is a structural hyperparameter already defined in the config.


