# Research Log
Started: 2026-05-13 23:10

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 2] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n2/iter_000_baseline


## Iter 0 — baseline — EM: 0.9918 (N=2)
**Hypothesis:** [Stream 2] baseline — RMM v5 default stack
**Wall time:** 34.7 min
**Result:** EM=0.9918 vs prev best=-1.0000
**Metric source:** all_results


## >>> N-level advanced to N=4 <<<
Previous N achieved EM=0.9918 >= threshold 0.95.


## Iter 1 — RUNNING — N=4
**Hypothesis:** Increasing write_value_dim to 256 will expand the effective memory capacity per write vector without violating the state_size constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_001_wvdim_256_sweep


## Iter 1 — kept — EM: 0.1872 (N=4)
**Hypothesis:** Increasing write_value_dim to 256 will expand the effective memory capacity per write vector without violating the state_size constraint.
**Wall time:** 71.3 min
**Result:** EM=0.1872 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** The directions explicitly flag write_value_dim as the primary intended capacity knob and current biggest miss. Scaling it tests the throughput vs. capacity trade-off in the pool-1tps regime.


## Iter 2 — RUNNING — N=4
**Hypothesis:** Setting num_memory_vectors to 4 and switching write_mode to cross_attn will multiply write throughput per segment while maintaining parallel-prefill compatibility.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_002_memvec_4_crosswrite


## Iter 2 — reverted — EM: 0.1522 (N=4)
**Hypothesis:** Setting num_memory_vectors to 4 and switching write_mode to cross_attn will multiply write throughput per segment while maintaining parallel-prefill compatibility.
**Wall time:** 71.2 min
**Result:** EM=0.1522 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** With tokens_per_segment locked at 1, increasing M is the only viable path to scale write capacity. cross_attn is required to structurally support M>1 writes.


## Iter 3 — RUNNING — N=4
**Hypothesis:** Splitting the GDN recurrent state into two parallel streams of width 16 each will improve gradient flow and state utilization compared to a single width-32 stream.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_003_dual_stream_gdn_16


## Iter 3 — FAILED — N=4
**Error:** experiment error: Experiment script exited with code 1
--- train.log tail (/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_003_dual_stream_gdn_16/train.log) ---
Traceback (most recent call last):
  File "/cephfs/home/bulatov/envs/gpu8/bin/accelerate", line 8, in <module>
    sys.exit(main())
             ^^^^^^
  File "/cephfs/home/bulatov/envs/gpu8/lib/python3.11/site-packages/accelerate/commands/accelerate_cli.py", line 50, in main
    args.func(args)
  File "/cephfs/home/bulatov/envs/gpu8/lib/python3.11/site-packages/accelerate/commands/launch.py", line 1235, in launch_command
    simple_launcher(args)
  File "/cephfs/home/bulatov/envs/gpu8/lib/python3.11/site-packages/accelerate/commands/launch.py", line 823, in simple_launcher
    raise subprocess.CalledProcessError(returncode=process.returncode, cmd=cmd)
subprocess.CalledProcessError: Command '['/cephfs/home/bulatov/envs/gpu8/bin/python3.11', 'run_rmm_on_kv_retrieval-v5p1.py', '--exp_path', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_003_dual_stream_gdn_16', '--per_device_batch_size', '64', '--gradient_accumulation_steps', '1', '--total_batch_size', '64', '--data_path', './data/N4-K2V2-V62_1M', '--tokenizer_path', './tokenizers/kv_alphabet_62/', '--learning_rate', '3e-4', '--n_layer', '4', '--n_head', '4', '--n_embd', '128', '--n_pairs', '4', '--n_keys', '2', '--n_values', '2', '--base_model', 'llama', '--fla_layer', 'GatedDeltaNet', '--state_size', '32', '--expand_v', '2.0', '--conv_kernel', '4', '--num_memory_vectors', '4', '--write_mode', 'cross_attn', '--read_mode', 'unpool', '--tokens_per_segment', '1', '--max_steps', '25000', '--eval_steps', '500', '--logging_steps', '500', '--warmup_steps', '10000', '--early_stopping_patience', '20', '--seed', '142']' returned non-zero exit status 1.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_003_dual_stream_gdn_16
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=4
**Hypothesis:** Replacing the last-dim-only rotation with a full state-mixing orthogonal matrix will enhance long-range dependency tracking across the GDN state.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_004_full_orthogonal_rotation


## Iter 4 — reverted — EM: 0.1652 (N=4)
**Hypothesis:** Replacing the last-dim-only rotation with a full state-mixing orthogonal matrix will enhance long-range dependency tracking across the GDN state.
**Wall time:** 71.3 min
**Result:** EM=0.1652 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** Re-introducing a smarter OrthogonalRotation is explicitly called out to improve state mixing beyond the current restricted implementation.


## Iter 5 — RUNNING — N=4
**Hypothesis:** Enabling write_residual will provide a direct, un-shifted memory read path that improves retrieval accuracy for immediate context segments.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_005_write_residual_on


## Iter 5 — reverted — EM: 0.1354 (N=4)
**Hypothesis:** Enabling write_residual will provide a direct, un-shifted memory read path that improves retrieval accuracy for immediate context segments.
**Wall time:** 58.0 min
**Result:** EM=0.1354 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** The directions suggest trying write_residual=true as a low-cost architectural shortcut to boost EM by adding a second read pathway for the current segment.


## Iter 6 — RUNNING — N=4
**Hypothesis:** Reordering the parallel path to READ→ATTN→WRITE will allow the attention mechanism to attend to already-updated memory, improving contextual alignment.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_006_read_attn_write_order


## Iter 6 — reverted — EM: 0.1436 (N=4)
**Hypothesis:** Reordering the parallel path to READ→ATTN→WRITE will allow the attention mechanism to attend to already-updated memory, improving contextual alignment.
**Wall time:** 72.0 min
**Result:** EM=0.1436 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** Layer-order experiments are encouraged to probe information flow dynamics; shifting reads before writes tests whether pre-updated memory yields better attention queries.


## Iter 7 — RUNNING — N=4
**Hypothesis:** Increasing expand_v to 2.0 and conv_kernel to 4 will broaden the receptive field of value projections, aiding pattern generalization for associative retrieval.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_007_expandv_2_conv4


## Iter 7 — kept — EM: 0.2020 (N=4)
**Hypothesis:** Increasing expand_v to 2.0 and conv_kernel to 4 will broaden the receptive field of value projections, aiding pattern generalization for associative retrieval.
**Wall time:** 78.9 min
**Result:** EM=0.2020 vs prev best=0.1872
**Metric source:** all_results
**Rationale:** These are listed as unlocked knobs to sweep; testing expanded dimensions and larger conv kernels probes representational capacity limits without altering core recurrence.


## Iter 8 — RUNNING — N=4
**Hypothesis:** Reducing warmup_steps from 10000 to 2000 will let the model reach full learning rate faster, improving convergence on the associative retrieval task.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_008_warmup_2000


## Iter 8 — reverted — EM: 0.1396 (N=4)
**Hypothesis:** Reducing warmup_steps from 10000 to 2000 will let the model reach full learning rate faster, improving convergence on the associative retrieval task.
**Wall time:** 67.2 min
**Result:** EM=0.1396 vs prev best=0.2020
**Metric source:** all_results
**Rationale:** The current warmup_steps of 10000 consumes 40% of the 25000 total training steps, meaning the model spends most of training at a suppressed learning rate. Reducing to 2000 (8% of training) still provides sufficient warmup for stability while giving the model 18000 more steps at full learning rate for effective convergence on the N=4 retrieval task.


## Iter 9 — RUNNING — N=4
**Hypothesis:** Switching read_mode from unpool to cross_attn will give the memory reader learnable Q/K/V projections instead of raw token-state dot-products, producing more discriminative attention patterns over memory vectors.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_009_cross_attn_reader


## Iter 9 — reverted — EM: 0.1322 (N=4)
**Hypothesis:** Switching read_mode from unpool to cross_attn will give the memory reader learnable Q/K/V projections instead of raw token-state dot-products, producing more discriminative attention patterns over memory vectors.
**Wall time:** 74.5 min
**Result:** EM=0.1322 vs prev best=0.2020
**Metric source:** all_results
**Rationale:** The current unpool reader computes attention as matmul(token_states, k_proj(memory)), using raw post-attention token embeddings as queries directly. The cross_attn reader uses learnable Q/K/V projections via LlamaCrossAttention, allowing the model to transform token states into an optimal query space for memory retrieval. This added expressivity should improve EM on the associative retrieval task.


## Iter 10 — RUNNING — N=4
**Hypothesis:** Adding a sigmoid-gated learnable scalar to the GDN skip connection in RecurrentLayerWithSkip will let the model dynamically control how much recurrent output to blend, improving retrieval accuracy over the unconditional residual.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_010_gated_gdn_skip


## Iter 10 — kept — EM: 0.2116 (N=4)
**Hypothesis:** Adding a sigmoid-gated learnable scalar to the GDN skip connection in RecurrentLayerWithSkip will let the model dynamically control how much recurrent output to blend, improving retrieval accuracy over the unconditional residual.
**Wall time:** 70.8 min
**Result:** EM=0.2116 vs prev best=0.2020
**Metric source:** all_results
**Rationale:** The current RecurrentLayerWithSkip always computes hidden_states + out_tensor, forcing the GDN contribution to be fully additive at every layer. For associative retrieval, some layers may benefit from suppressing the recurrent signal when the memory path already provides sufficient information. A per-layer gate initialized near 1.0 preserves the default behavior while allowing learned adaptation.


## Iter 11 — RUNNING — N=4
**Hypothesis:** Adding RMSNorm to memory states before the reader's key/value projections will normalize the attention scale between token queries and memory keys, producing better-calibrated attention distributions.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_2/n4/iter_011_mem_norm_in_reader


## Iter 11 — reverted — EM: 0.1454 (N=4)
**Hypothesis:** Adding RMSNorm to memory states before the reader's key/value projections will normalize the attention scale between token queries and memory keys, producing better-calibrated attention distributions.
**Wall time:** 58.8 min
**Result:** EM=0.1454 vs prev best=0.2116
**Metric source:** all_results
**Rationale:** The reader path normalizes token states with read_norm but leaves memory states unnormalized, creating an attention scale mismatch. Normalizing memory states will ensure well-calibrated softmax attention between queries and keys, improving retrieval discrimination across memory slots.


