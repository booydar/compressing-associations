# Experiment Summary

## Iter 9 | reverted | N=4
- Hypothesis: Switching read_mode to cross_attn with multiple heads improves memory retrieval precision by allowing tokens to selectively attend to relevant memory vectors.
- Target: .autoresearch/experiment_config.yaml
- EM: 0.1830
- Success: Change ran successfully and produced a measurable result.
- Weaknesses: It did not improve over the previous best.
- Failures: No executor or run failure, but the hypothesis underperformed.
- Rationale: All N=4 experiments collapsed while N=2 achieved EM=0.989. The unpool read mode uses simple softmax attention without learned query projections. Cross-attention with multiple heads could provide more expressive memory readout, enabling better discrimination between memory slots during retrieval.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_009_cross_attn_read_4heads_n4

## Iter 16 | failed | N=4
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: In _forward_parallel, the GDN processes all S*M vectors as one sequence, so its hidden state bleeds across segment boundaries. At N=4 with S=3 context segments and M=4 vectors, segment 3's vectors are processed with a hidden state saturated by segments 1-2, blurring slot identity. N=2 succeeds because fewer segments mean less interference. Per-segment cache reset processes each segment's M vectors with a fresh hidden state while preserving within-segment recurrence, preventing cross-segment corruption of stored keys.
- exp_path: 

## Iter 17 | failed | N=4
- Hypothesis: FAILED: executor failed after 4 attempts: The previous iteration's training run failed with the following error. Take this into account when applying the change; if your edit must avoid the same failure, adjust accordingly.

executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: The previous iteration's training run failed with the following error. Take this into account when applying the change; if your edit must avoid the same failure, adjust accordingly.

executor failed after 4 attempts: None
- Rationale: Token accuracy reaches ~0.43 but EM stays at 0, meaning the reader retrieves some tokens but cannot combine all 4 simultaneously. The current reader is just Q/K/V projections + output linear — no non-linear transformation of the attended output. All 16 prior experiments targeted the GDN, memory normalization, or attention scaling, but none modified the reader's internal capacity. An FFN after cross-attention lets the reader learn complex combinations of slot information, similar to how transformer layers use ATTN→FFN stacks.
- exp_path: 

