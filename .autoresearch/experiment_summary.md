
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

