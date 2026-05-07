# Experiment Summary

## Iter 0 | failed | N=16
- Hypothesis: [Stream 0] baseline — exact copy of v2
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn-autor-v5/runs/autoresearch/stream_0/n16/iter_000_baseline

## Iter 1 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: Multiplicative dynamics often preserve signal integrity better than additive updates in low-dimensional recurrent states.
- exp_path: 

## Iter 1 | failed | N=16
- Hypothesis: FAILED: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Target: modeling_rmt/huggingface_rmm_v2.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: Executor error: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF']' timed out after 900 seconds
- Rationale: LRU architectures utilize diagonal state matrices that can capture different time scales more efficiently than standard delta networks.
- exp_path: 

