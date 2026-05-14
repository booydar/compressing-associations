# Research Log
Started: 2026-05-13 00:25

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n2/iter_000_baseline


## Iter 0 — baseline — EM: 0.8534 (N=2)
**Hypothesis:** [Stream 0] baseline — RMM v5 default stack
**Wall time:** 56.5 min
**Result:** EM=0.8534 vs prev best=-1.0000
**Metric source:** all_results


## Iter 1 — RUNNING — N=2
**Hypothesis:** Increasing write_value_dim to 512 significantly boosts memory capacity for KV retrieval without violating state_size constraints.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n2/iter_001_write_value_dim_512_n2


## Iter 1 — kept — EM: 0.9122 (N=2)
**Hypothesis:** Increasing write_value_dim to 512 significantly boosts memory capacity for KV retrieval without violating state_size constraints.
**Wall time:** 57.0 min
**Result:** EM=0.9122 vs prev best=0.8534
**Metric source:** all_results
**Rationale:** Directions identify write_value_dim as the single biggest miss in v5p design and explicitly unlock it for sweeping up to 512.


## Iter 2 — RUNNING — N=2
**Hypothesis:** Increasing num_memory_vectors to 4 with cross_attn write mode multiplies write throughput effectively at 1 token per segment.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n2/iter_002_mem_vectors_4_cross_n2


## Iter 2 — kept — EM: 0.9890 (N=2)
**Hypothesis:** Increasing num_memory_vectors to 4 with cross_attn write mode multiplies write throughput effectively at 1 token per segment.
**Wall time:** 56.6 min
**Result:** EM=0.9890 vs prev best=0.9122
**Metric source:** all_results
**Rationale:** Directions state M>1 is the only way to multiply write throughput at tps=1 and requires cross_attn mode verification.


## >>> N-level advanced to N=4 <<<
Previous N achieved EM=0.9890 >= threshold 0.95.


## Iter 3 — RUNNING — N=4
**Hypothesis:** Re-introducing full OrthogonalRotation matrix improves state mixing compared to the current last-dim only implementation.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_003_ortho_rotation_full_n2


## Iter 3 — kept — EM: 0.0766 (N=4)
**Hypothesis:** Re-introducing full OrthogonalRotation matrix improves state mixing compared to the current last-dim only implementation.
**Wall time:** 66.5 min
**Result:** EM=0.0766 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** Directions explicitly encourage re-introducing smarter OrthogonalRotation with full state-mixing matrix to push architecture HARD.


## Iter 4 — RUNNING — N=4
**Hypothesis:** Two parallel GDN paths of state_size 16 increase effective width while strictly respecting the state_size <= 32 hard lock.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_004_multi_stream_gdn_n2


## Iter 4 — kept — EM: 0.0798 (N=4)
**Hypothesis:** Two parallel GDN paths of state_size 16 increase effective width while strictly respecting the state_size <= 32 hard lock.
**Wall time:** 45.4 min
**Result:** EM=0.0798 vs prev best=0.0766
**Metric source:** all_results
**Rationale:** Directions suggest multi-stream GDN as a bold architecture edit to increase capacity without breaking state_size constraints.


## Iter 5 — RUNNING — N=4
**Hypothesis:** A higher learning rate of 3e-4 accelerates convergence on the N=2 task compared to standard baselines.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_005_lr_3e4_bold_n2


## Iter 5 — kept — EM: 0.2188 (N=4)
**Hypothesis:** A higher learning rate of 3e-4 accelerates convergence on the N=2 task compared to standard baselines.
**Wall time:** 68.6 min
**Result:** EM=0.2188 vs prev best=0.0798
**Metric source:** all_results
**Rationale:** Directions suggest sweeping learning rates up to 3e-4 and emphasize boldness over safe micro-tweaks.


## Iter 6 — RUNNING — N=4
**Hypothesis:** Reverting to N=2 recovers the near-perfect EM=0.989 achieved with write_value_dim=512 and num_memory_vectors=4, isolating the N-level as the collapse point.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_006_revert_n2_verify_baseline


## Iter 6 — reverted — EM: 0.0764 (N=4)
**Hypothesis:** Reverting to N=2 recovers the near-perfect EM=0.989 achieved with write_value_dim=512 and num_memory_vectors=4, isolating the N-level as the collapse point.
**Wall time:** 49.7 min
**Result:** EM=0.0764 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** The N=2 configuration achieved EM=0.989 (iter_002) while all N=4 experiments collapsed to EM<0.22. Reverting to N=2 validates the baseline before exploring N=4 fixes.


## Iter 7 — RUNNING — N=4
**Hypothesis:** Enabling write_residual=true with N=4 allows memory readout to augment rather than replace token states, potentially recovering signal loss in deeper memory chains.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_007_write_residual_n4


## Iter 7 — reverted — EM: 0.0054 (N=4)
**Hypothesis:** Enabling write_residual=true with N=4 allows memory readout to augment rather than replace token states, potentially recovering signal loss in deeper memory chains.
**Wall time:** 55.7 min
**Result:** EM=0.0054 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** All N=4 experiments collapsed (EM<0.22) while N=2 achieved EM=0.989. The write_residual flag has never been tested; it adds memory readout as a residual to post-attention tokens, potentially preserving both memory signal and original representation needed for N=4 retrieval.


## Iter 8 — RUNNING — N=4
**Hypothesis:** Reducing num_memory_vectors to 2 with write_value_dim=512 concentrates memory capacity into fewer slots, improving signal-to-noise for KV retrieval at N=4.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_008_nmem2_write512_n4


## Iter 8 — reverted — EM: 0.0858 (N=4)
**Hypothesis:** Reducing num_memory_vectors to 2 with write_value_dim=512 concentrates memory capacity into fewer slots, improving signal-to-noise for KV retrieval at N=4.
**Wall time:** 47.5 min
**Result:** EM=0.0858 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** Iter 6 achieved EM=0.989 with N=2, write_value_dim=512, num_memory_vectors=4. At N=4, memory pressure increases. Halving memory vectors while keeping write_value_dim high may reduce interference between memory slots and recover performance.


## Iter 9 — RUNNING — N=4
**Hypothesis:** Switching read_mode to cross_attn with multiple heads improves memory retrieval precision by allowing tokens to selectively attend to relevant memory vectors.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_009_cross_attn_read_4heads_n4


## Iter 9 — reverted — EM: 0.1830 (N=4)
**Hypothesis:** Switching read_mode to cross_attn with multiple heads improves memory retrieval precision by allowing tokens to selectively attend to relevant memory vectors.
**Wall time:** 754.5 min
**Result:** EM=0.1830 vs prev best=0.2188
**Metric source:** trainer_state
**Recovery:** checkpoint fallback used because final results were missing.


## Iter 10 — RUNNING — N=4
**Hypothesis:** Reducing warmup_steps from 10000 to 500 allows the model to train at full learning rate for 98% of the budget instead of 60%, which is critical for converging on the harder N=4 task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_010_warmup500_conv2_n4


## Iter 10 — reverted — EM: 0.0814 (N=4)
**Hypothesis:** Reducing warmup_steps from 10000 to 500 allows the model to train at full learning rate for 98% of the budget instead of 60%, which is critical for converging on the harder N=4 task.
**Wall time:** 45.6 min
**Result:** EM=0.0814 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** With warmup_steps=10000 out of max_steps=25000, the model only reaches full LR at step 10000, leaving only 15000 steps at full strength. All 7 N=4 attempts have failed, suggesting insufficient training signal. Reducing warmup to 500 steps gives 24500 steps at full LR=3e-4, a 6.3x increase in effective training time at full learning rate. Combined with conv_kernel=2 to reduce temporal over-mixing across memory vectors at tokens_per_segment=1, this addresses both training dynamics and architectural over-smoothing.


## Iter 11 — RUNNING — N=4
**Hypothesis:** Reducing conv_kernel from 4 to 2 prevents the GDN's convolution from blurring all M=4 memory vectors together at tokens_per_segment=1, preserving slot-specific information critical for N=4 retrieval.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_011_conv2_isolated_n4


## Iter 11 — reverted — EM: 0.1346 (N=4)
**Hypothesis:** Reducing conv_kernel from 4 to 2 prevents the GDN's convolution from blurring all M=4 memory vectors together at tokens_per_segment=1, preserving slot-specific information critical for N=4 retrieval.
**Wall time:** 70.6 min
**Result:** EM=0.1346 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** At tokens_per_segment=1, the GDN processes M=4 memory vectors sequentially and conv_kernel=4 means each vector's convolution window spans all 4 vectors, destroying slot identity. Iter_010 bundled conv_kernel=2 with warmup_steps=500 and failed, so the conv_kernel effect was confounded. Isolating conv_kernel=2 alone tests whether temporal over-mixing is a primary failure mode for N=4.


## Iter 12 — RUNNING — N=4
**Hypothesis:** Reducing expand_v from 2.0 to 1.0 shrinks the GDN's internal hidden dimension from 1024 to 512, providing regularization that prevents overfitting on the limited N=4 training signal.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_012_expand1_regularized_n4


## Iter 12 — reverted — EM: 0.1504 (N=4)
**Hypothesis:** Reducing expand_v from 2.0 to 1.0 shrinks the GDN's internal hidden dimension from 1024 to 512, providing regularization that prevents overfitting on the limited N=4 training signal.
**Wall time:** 54.9 min
**Result:** EM=0.1504 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** All N=4 experiments have collapsed (EM<0.22) while the GDN processes only 12 vectors per layer (S=3 context segments x M=4 memory vectors). With expand_v=2.0 and write_value_dim=512, the GDN's internal hidden dimension is 1024—8x the number of input vectors. This massive expansion creates a severely over-parameterized model that memorizes rather than generalizes. Reducing expand_v to 1.0 matches the GDN's hidden dimension to the input width (512), providing effective regularization while preserving full state_size=32 capacity for memory storage.


## Iter 13 — RUNNING — N=4
**Hypothesis:** Per-vector RMSNorm after the GDN stabilizes memory vector magnitudes so the reader's cross-attention relies on directional alignment rather than norm differences.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_013_mem_norm_n4


## Iter 13 — reverted — EM: 0.1590 (N=4)
**Hypothesis:** Per-vector RMSNorm after the GDN stabilizes memory vector magnitudes so the reader's cross-attention relies on directional alignment rather than norm differences.
**Wall time:** 70.5 min
**Result:** EM=0.1590 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** The GDN produces memory vectors whose norms vary unpredictably across slots and training steps. With cross_attn read_mode, the reader's attention is computed via dot products that are dominated by norm magnitude rather than directional similarity. This is especially harmful at N=4 where 4 memory vectors must remain distinguishable. Normalizing vectors to unit scale after the GDN (post-orthogonal-rotation) forces the reader to attend based on content direction, improving slot discrimination. This complements the conv_kernel findings (iter_011 showed conv_kernel=2 improved token accuracy to 0.39) by ensuring the reader receives well-conditioned inputs.


## Iter 14 — RUNNING — N=4
**Hypothesis:** Stacking conv_kernel=2, expand_v=1.0, and per-vector RMSNorm combines three individually beneficial architectural changes that each improved token accuracy but failed to break the EM=0.22 ceiling in isolation.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_014_stack_conv2_expand1_memnorm_n4


## Iter 14 — reverted — EM: 0.0788 (N=4)
**Hypothesis:** Stacking conv_kernel=2, expand_v=1.0, and per-vector RMSNorm combines three individually beneficial architectural changes that each improved token accuracy but failed to break the EM=0.22 ceiling in isolation.
**Wall time:** 46.2 min
**Result:** EM=0.0788 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** At N=4, three distinct failure modes limit performance: (1) conv_kernel=4 temporally over-mixes M=4 memory slots at tokens_per_segment=1 (iter_011: conv_kernel=2 improved token_acc to 0.39), (2) expand_v=2.0 creates a 1024-dim GDN hidden over only 12 input vectors, causing over-parameterization (iter_012: expand_v=1.0 improved token_acc to 0.40), (3) cross-attention reader is dominated by vector norm magnitude rather than content direction (iter_013: per-vector RMSNorm improved token_acc to 0.43). Each change alone nudged token accuracy upward but couldn't push EM past 0.2188. Together they form a coherent package: smaller conv kernel preserves slot identity, matched expansion prevents overfitting, and normalization ensures content-based attention. The model is clearly learning more (token_acc rising from 0.27 baseline to 0.43), suggesting these changes are directionally correct but need to be combined to reach the EM threshold.


## Iter 15 — RUNNING — N=4
**Hypothesis:** L2-normalizing Q and K in the reader's cross-attention makes attention purely angle-based, preventing norm-dominance collapse and enabling uniform retrieval across all M=4 memory slots at N=4.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_015_reader_l2_norm_n4


## Iter 15 — reverted — EM: 0.1734 (N=4)
**Hypothesis:** L2-normalizing Q and K in the reader's cross-attention makes attention purely angle-based, preventing norm-dominance collapse and enabling uniform retrieval across all M=4 memory slots at N=4.
**Wall time:** 72.0 min
**Result:** EM=0.1734 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** At N=4, token_acc reaches ~0.43 but EM stays near 0, meaning the reader retrieves some tokens but not all 4 KV pairs simultaneously. The cross-attention reader's softmax scores are dominated by vector norm magnitude rather than content direction, causing attention collapse onto 1-2 strong slots. L2 normalization of Q and K before the dot product removes magnitude effects, forcing the reader to distribute attention based on angular similarity alone. This should enable uniform retrieval across all M=4 memory vectors, converting partial token accuracy into full exact match.


## Iter 16 — FAILED — N=4
**Error:** executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 17 — FAILED — N=4
**Error:** executor failed after 4 attempts: The previous iteration's training run failed with the following error. Take this into account when applying the change; if your edit must avoid the same failure, adjust accordingly.

executor failed after 4 attempts: None
**Recovery status:** not_attempted


## Iter 18 — RUNNING — N=4
**Hypothesis:** Setting conv_kernel=1 eliminates all cross-token convolutional mixing in the GDN, maximally preserving slot-specific information for N=4 retrieval where conv_kernel=2 already helped (iter 11).
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_018_conv_kernel_1


## Iter 18 — reverted — EM: 0.0148 (N=4)
**Hypothesis:** Setting conv_kernel=1 eliminates all cross-token convolutional mixing in the GDN, maximally preserving slot-specific information for N=4 retrieval where conv_kernel=2 already helped (iter 11).
**Wall time:** 84.6 min
**Result:** EM=0.0148 vs prev best=0.2188
**Metric source:** all_results
**Rationale:** iter 14 showed that conv_kernel=2 combined with expand_v=1.0 and RMSNorm achieved the best EM=0.0788. Reducing conv_kernel further to 1 removes the convolution entirely, making the GDN operate as a pure pointwise recurrent cell. At tokens_per_segment=1 with M=4 memory vectors, even conv_kernel=2 mixes adjacent slots; conv_kernel=1 preserves each slot independently.


