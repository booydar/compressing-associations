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


