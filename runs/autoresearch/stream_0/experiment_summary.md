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

