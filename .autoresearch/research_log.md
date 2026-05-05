
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


## Iter 1 — kept — EM: 0.2512 (N=16)
**Hypothesis:** Increase n_head from 4 to 8 to improve multi-association tracking capacity while keeping state_size constant at 32
**Wall time:** 120.0 min
**Result:** EM=0.2512 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_001_increase_n_head_to_8', '16', '25000']' timed out after 7199.9999805500265 seconds
**Rationale:** With state_size fixed at 32, increasing n_head from 4 to 8 reduces head_dim from 8 to 4, providing more parallel attention heads. This should improve the model's ability to track multiple key-value associations simultaneously in the retrieval task, as each head can specialize in different association patterns.


## Iter 0 — RECOVERED — N=16
**Recovered from:** trainer_state
**Recovered EM:** 0.2072


## Iter 1 — kept — EM: 0.2830 (N=16)
**Hypothesis:** Increase expand_v from 4.0 to 6.0 to give the FLA layer more capacity to store associative mappings
**Wall time:** 120.0 min
**Result:** EM=0.2830 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_2/n16/iter_001_expand_v_six', '16', '25000']' timed out after 7199.99998121988 seconds
**Rationale:** The current expand_v=4.0 may be too constrained for learning the key-value associations. Increasing to 6.0 expands the value projection dimension, providing more representational capacity without changing the core state_size constraint. This is a low-risk hyperparameter adjustment with clear theoretical motivation.


## Iter 0 — RECOVERED — N=16
**Recovered from:** trainer_state
**Recovered EM:** 0.2072


## Iter 1 — kept — EM: 0.1822 (N=16)
**Hypothesis:** Reduce n_head from 4 to 2 to increase head_dim from 8 to 16 while keeping state_size constant at 32
**Wall time:** 120.0 min
**Result:** EM=0.1822 vs prev best=-1.0000
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_001_reduce_n_head_to_2', '16', '25000']' timed out after 7199.9999817512 seconds
**Rationale:** With state_size fixed at 32, reducing n_head from 4 to 2 increases head_dim from 8 to 16. Wider heads may better capture long-range dependencies and complex associative patterns in the retrieval task, complementing the parallel head approach tested in stream 1.


## Iter 0 — RECOVERED — N=16
**Recovered from:** trainer_state
**Recovered EM:** 0.2142


## Iter 1 — RUNNING — N=16
**Hypothesis:** Increase conv_kernel from 2 to 4 to capture longer local context within key-value pairs
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_001_increase_conv_kernel_to_4


## Iter 2 — RUNNING — N=16
**Hypothesis:** Increase state_size from 32 to 48 to provide more recurrent memory capacity for storing key-value associations
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_2/n16/iter_002_increase_state_size_to_48


## Iter 2 — RUNNING — N=16
**Hypothesis:** Reduce warmup_steps from 10000 to 5000 to allow more training at full learning rate
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_002_reduce_warmup_to_5000


## Iter 2 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_002_reduce_warmup_to_5000
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 2 — RUNNING — N=16
**Hypothesis:** Increase n_head from 4 to 8 to improve multi-association tracking capacity while keeping state_size constant at 32
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_002_increase_n_head_to_8


## Iter 2 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_002_increase_n_head_to_8
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Increase expand_v from 4.0 to 6.0 to complement n_head=8 with more value projection capacity per head
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_003_expand_v_6_with_n_head_8


## Iter 3 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_003_expand_v_6_with_n_head_8
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — reverted — EM: 0.0002 (N=16)
**Hypothesis:** Increase conv_kernel from 2 to 4 to capture longer local context within key-value pairs
**Wall time:** 41.4 min
**Result:** EM=0.0002 vs prev best=0.2006
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Experiment script exited with code 1
**Rationale:** The current conv_kernel=2 limits the short convolution to only 2 tokens, which may be too restrictive for capturing local patterns in the key-value association task. Increasing to 4 (the maximum allowed) expands the receptive field of the FLA layer's local convolution, potentially improving the model's ability to learn associations between adjacent key and value tokens.


## Iter 3 — RUNNING — N=16
**Hypothesis:** Increase expand_v from 4.0 to 6.0 to give the FLA layer more capacity to store associative mappings
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_003_expand_v_to_6_0


## Iter 3 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_003_expand_v_to_6_0
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=16
**Hypothesis:** Combine n_head=8 with expand_v=6.0 to maximize FLA layer capacity for multi-association tracking
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_004_n_head_8_expand_v_6


## Iter 4 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_004_n_head_8_expand_v_6
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 2 — RUNNING — N=16
**Hypothesis:** Combine n_head=8 with expand_v=6.0 to maximize both parallel head capacity and value projection dimension
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_002_n_head_8_expand_v_6_combined


## Iter 2 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_002_n_head_8_expand_v_6_combined
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=16
**Hypothesis:** Combine n_head=8 with expand_v=6.0 to maximize FLA layer capacity for multi-association tracking
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_004_n_head_8_expand_v_6


## Iter 4 — FAILED — N=16
**Error:** experiment error: Experiment script exited with code 1
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_004_n_head_8_expand_v_6
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 2 — kept — EM: 0.4274 (N=16)
**Hypothesis:** Increase state_size from 32 to 48 to provide more recurrent memory capacity for storing key-value associations
**Wall time:** 120.0 min
**Result:** EM=0.4274 vs prev best=0.2830
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.
**Run error:** experiment error: Command '['bash', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/scripts/run_autoresearch_exp.sh', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_2/n16/iter_002_increase_state_size_to_48', '16', '25000']' timed out after 7199.999975349987 seconds
**Rationale:** With expand_v already increased to 6.0, the FLA layer has expanded value projection capacity. Increasing state_size from 32 to 48 provides more total recurrent memory (num_heads * head_dim) for storing key-value associations across segments. This complements the expand_v increase by expanding the core memory state itself.


