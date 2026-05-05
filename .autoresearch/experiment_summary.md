
## Iter 0 | failed | N=16
- Hypothesis: [Stream 0] baseline — exact copy of v2
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_000_baseline

## Iter 2 | failed | N=16
- Hypothesis: Reduce warmup_steps from 10000 to 5000 to allow more training at full learning rate
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: With warmup_steps=10000 out of max_steps=25000, only 60% of training occurs at full learning rate. Reducing warmup to 5000 (20% of steps) gives 80% of training at full LR, potentially improving convergence. This is a low-risk hyperparameter adjustment that complements the successful expand_v=6.0 configuration.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_002_reduce_warmup_to_5000

## Iter 2 | failed | N=16
- Hypothesis: Increase n_head from 4 to 8 to improve multi-association tracking capacity while keeping state_size constant at 32
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Stream 3 iter 1 showed that reducing n_head to 2 hurt performance (EM=0.1822 vs baseline). Stream 1 tested increasing n_head to 8 and achieved EM=0.2512, suggesting more heads helps. With state_size=32 fixed, increasing n_head from 4 to 8 reduces head_dim from 8 to 4, providing more parallel attention heads to track multiple key-value associations simultaneously.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_002_increase_n_head_to_8

## Iter 3 | failed | N=16
- Hypothesis: Increase expand_v from 4.0 to 6.0 to complement n_head=8 with more value projection capacity per head
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Stream 1's n_head=8 configuration achieved EM=0.2512, showing improvement over baseline. With more heads but smaller head_dim (4), each head has less capacity to store associations. Increasing expand_v from 4.0 to 6.0 expands the value projection dimension, giving each of the 8 heads more representational capacity. This combination should outperform either change alone.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_003_expand_v_6_with_n_head_8

## Iter 3 | failed | N=16
- Hypothesis: Increase expand_v from 4.0 to 6.0 to give the FLA layer more capacity to store associative mappings
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Stream 2 achieved the best EM score (0.283) with expand_v=6.0, demonstrating that expanding the value projection dimension improves associative retrieval performance. Stream 3 is currently at the baseline expand_v=4.0 configuration. Increasing to 6.0 provides more representational capacity without changing the state_size constraint, following the successful pattern established in stream 2.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_003_expand_v_to_6_0

## Iter 4 | failed | N=16
- Hypothesis: Combine n_head=8 with expand_v=6.0 to maximize FLA layer capacity for multi-association tracking
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: n_head=8 achieved EM=0.2512 and expand_v=6.0 achieved EM=0.283, both outperforming baseline. Combining more parallel heads (better multi-association tracking) with expanded value projections (more storage per head) should yield synergistic improvements. This tests whether the two capacity-increasing modifications compound positively.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_1/n16/iter_004_n_head_8_expand_v_6

## Iter 2 | failed | N=16
- Hypothesis: Combine n_head=8 with expand_v=6.0 to maximize both parallel head capacity and value projection dimension
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Stream 2 achieved EM=0.283 with expand_v=6.0 alone, while stream 1 achieved EM=0.2512 with n_head=8 alone. Stream 0 baseline (EM=0.2006) has neither improvement. Combining both changes should yield better performance than either alone, as more heads provide parallel tracking capacity while higher expand_v gives each head more representational power.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_0/n16/iter_002_n_head_8_expand_v_6_combined

## Iter 4 | failed | N=16
- Hypothesis: Combine n_head=8 with expand_v=6.0 to maximize FLA layer capacity for multi-association tracking
- Target: experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Both n_head=8 (EM=0.2512) and expand_v=6.0 (EM=0.283) individually outperformed baseline. Stream 3's previous attempts at each change separately failed. Combining more parallel heads for better multi-association tracking with expanded value projections for more storage per head should yield synergistic improvements in associative retrieval performance.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v4/runs/autoresearch/stream_3/n16/iter_004_n_head_8_expand_v_6

