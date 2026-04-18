## Iter 0 | failed | N=8
- Hypothesis: baseline — exact copy of v2
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_000_baseline
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_000_baseline

## Iter 1 | failed | N=8
- Hypothesis: The model needs more training steps to converge on the associative retrieval task.
- Target: .autoresearch/experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: Configuration error: missing required key 'pairs_per_segment'. Current exp_cfg keys: ['max_steps', 'eval_steps', 'logging_steps', 'warmup_steps', 'early_stopping_patience', 'n_layer', 'n_head', 'n_embd', 'n_mem_tokens', 'n_keys', 'n_values', 'base_model', 'learning_rate', 'batch_size', 'em_threshold']
- Rationale: The baseline experiment failed with no checkpoints - this is a training configuration issue. With max_steps=25000 and eval_steps=500, the model should have produced at least one checkpoint. However, the first experiment failed to establish any baseline. Increasing max_steps gives the model more opportunity to learn the associative patterns before evaluation.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_001

## Iter 2 | failed | N=8
- Hypothesis: FAILED: unhandled: git add failed: The following paths are ignored by one of your .gitignore files:
.autoresearch/artifacts
Use -f if you really want to add them.
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: git add failed: The following paths are ignored by one of your .gitignore files:
.autoresearch/artifacts
Use -f if you really want to add them.
- Rationale: (none)
- exp_path: 

## Iter 4 | failed | N=8
- Hypothesis: A learning rate sweep will identify the optimal training signal strength for the associative retrieval task, as the current fixed rate of 0.01 may be too high or too low for convergence.
- Target: .autoresearch/experiment_config.yaml
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_004: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_004
- Rationale: Hyperparameters have not been exhausted - only a learning rate sweep was attempted in iter_2 but failed due to a git issue, not training failure. The fixed learning_rate of 0.01 may be suboptimal; sweeping [0.0001, 0.0005, 0.001, 0.005, 0.01] will find the optimal value before considering architectural changes.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_004

## Iter 16 | failed | N=8
- Hypothesis: Replacing the scalar write_gate with an input-dependent gating mechanism will allow adaptive memory updates based on input content, improving retention of associative patterns.
- Target: modeling_rmt/huggingface_rmca_v3.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Hyperparameters have been exhausted: sweeps completed for learning_rate, n_mem_tokens, n_embd, warmup_steps, n_layer, batch_size, weight_decay, and n_head. Best EM achieved was 0.1246. Further hyperparameter tuning is unlikely to help as the bottleneck appears to be architectural - the fixed scalar write_gate cannot adapt to varying input patterns.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_016

## Iter 21 | failed | N=8
- Hypothesis: Replacing the fixed scalar write_gate with an adaptive gating mechanism that computes gate values from input features will enable the model to control memory writes based on content importance, improving associative pattern retention.
- Target: modeling_rmt/huggingface_rmca_v3.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
- Rationale: Hyperparameters have been exhausted: sweeps completed for learning_rate, n_mem_tokens, n_embd, warmup_steps, n_layer, batch_size, weight_decay, and n_head. Best EM achieved was 0.3876. Further hyperparameter tuning is unlikely to help as the scalar write_gate cannot adapt to varying input patterns - it applies uniform write strength regardless of input content importance.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-v2.4/runs-autoresearch/n8/iter_021

