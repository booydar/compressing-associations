# Research Log
Started: 2026-05-13 00:26

## Iter 0 — RUNNING — N=2
**Hypothesis:** [Stream 1] baseline — RMM v5 default stack
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline


## Iter 0 — FAILED — N=2
**Error:** could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 1 — RUNNING — N=2
**Hypothesis:** Increasing write_value_dim to 256 will significantly improve EM by expanding write capacity without violating state_size <= 32.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_001_write_val_dim_256_n2


## Iter 1 — kept — EM: 0.4924 (N=2)
**Hypothesis:** Increasing write_value_dim to 256 will significantly improve EM by expanding write capacity without violating state_size <= 32.
**Wall time:** 56.2 min
**Result:** EM=0.4924 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** Directions identify write_value_dim as the single biggest miss in v5p design and it is currently an unlocked capacity knob.


## Iter 2 — RUNNING — N=2
**Hypothesis:** Setting num_memory_vectors to 4 with cross_attn write_mode will maximize write throughput for pool-1tps regime.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_002_mem_vecs_4_cross_n2


## Iter 2 — kept — EM: 0.9922 (N=2)
**Hypothesis:** Setting num_memory_vectors to 4 with cross_attn write_mode will maximize write throughput for pool-1tps regime.
**Wall time:** 50.1 min
**Result:** EM=0.9922 vs prev best=0.4924
**Metric source:** all_results
**Rationale:** M>1 is the only way to multiply write throughput when tokens_per_segment=1 and cross_attn is required for M>1 to work.


## >>> N-level advanced to N=4 <<<
Previous N achieved EM=0.9922 >= threshold 0.95.


## Iter 3 — RUNNING — N=4
**Hypothesis:** Splitting state_size into two parallel GDN paths of width 16 increases effective non-linearity while respecting state_size <= 32 constraint.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_003_dual_stream_gdn_n2


## Iter 3 — FAILED — N=4
**Error:** experiment error: Experiment script exited with code 1
--- train.log tail (/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_003_dual_stream_gdn_n2/train.log) ---
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
subprocess.CalledProcessError: Command '['/cephfs/home/bulatov/envs/gpu8/bin/python3.11', 'run_rmm_on_kv_retrieval-v5p1.py', '--exp_path', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_003_dual_stream_gdn_n2', '--per_device_batch_size', '64', '--gradient_accumulation_steps', '1', '--total_batch_size', '64', '--data_path', './data/N4-K2V2-V62_1M', '--tokenizer_path', './tokenizers/kv_alphabet_62/', '--learning_rate', '3e-4', '--n_layer', '4', '--n_head', '4', '--n_embd', '128', '--n_pairs', '4', '--n_keys', '2', '--n_values', '2', '--base_model', 'llama', '--fla_layer', 'GatedDeltaNet', '--state_size', '32', '--expand_v', '2.0', '--conv_kernel', '4', '--num_memory_vectors', '1', '--write_mode', 'pool', '--read_mode', 'unpool', '--tokens_per_segment', '1', '--max_steps', '25000', '--eval_steps', '500', '--logging_steps', '500', '--warmup_steps', '10000', '--early_stopping_patience', '20', '--seed', '142']' returned non-zero exit status 1.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_003_dual_stream_gdn_n2
**Recovery status:** unresolved
**Next action:** planner will propose new change based on error.


## Iter 4 — RUNNING — N=4
**Hypothesis:** Enabling write_residual=true will improve EM by enriching post-attn token states with fresh memory from the current layer.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_004_write_residual_true_n2


## Iter 4 — kept — EM: 0.0760 (N=4)
**Hypothesis:** Enabling write_residual=true will improve EM by enriching post-attn token states with fresh memory from the current layer.
**Wall time:** 68.6 min
**Result:** EM=0.0760 vs prev best=-1.0000
**Metric source:** all_results
**Rationale:** write_residual is implemented in the model but never tested. It adds post-attn memory enrichment which could push EM beyond 0.9922 by allowing tokens to read their own layer's write output.


## Iter 5 — RUNNING — N=4
**Hypothesis:** Increasing num_memory_vectors to 8 will further improve EM by expanding memory bank capacity while maintaining the successful cross_attn+unpool read-write pairing.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_005_mem_vecs_8_cross_n2


## Iter 5 — kept — EM: 0.1544 (N=4)
**Hypothesis:** Increasing num_memory_vectors to 8 will further improve EM by expanding memory bank capacity while maintaining the successful cross_attn+unpool read-write pairing.
**Wall time:** 70.2 min
**Result:** EM=0.1544 vs prev best=0.0760
**Metric source:** all_results
**Rationale:** iter_002 with N=2, num_memory_vectors=4 achieved EM=0.9922. write_residual=true (iter_004) caused severe degradation to 0.076. Increasing M from 4 to 8 expands memory capacity without changing the successful architecture. write_residual should remain false.


## Iter 6 — RUNNING — N=4
**Hypothesis:** Returning to num_memory_vectors=4 with N=2 will recover the EM=0.9922 peak by restoring the proven configuration that balanced memory capacity with signal-to-noise ratio.
**exp_path:** /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_006_recover_peak_n2_m4


## Iter 6 — kept — EM: 0.2280 (N=4)
**Hypothesis:** Returning to num_memory_vectors=4 with N=2 will recover the EM=0.9922 peak by restoring the proven configuration that balanced memory capacity with signal-to-noise ratio.
**Wall time:** 69.3 min
**Result:** EM=0.2280 vs prev best=0.1544
**Metric source:** all_results
**Rationale:** iter_002 with N=2, num_memory_vectors=4 achieved EM=0.9922. Both N=4 experiments (iter_004, iter_005) severely degraded to EM<0.16. The current config has num_memory_vectors=8 which was only tested at N=4. Returning to the proven N=2, M=4 configuration with write_value_dim=256 should recover peak performance.


