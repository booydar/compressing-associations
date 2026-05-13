# Experiment Summary

## Iter 0 | failed | N=2
- Hypothesis: [Stream 1] baseline — RMM v5 default stack
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: could not recover metrics from /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline: No checkpoints found in /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline
- Rationale: (none)
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n2/iter_000_baseline

## Iter 3 | failed | N=4
- Hypothesis: Splitting state_size into two parallel GDN paths of width 16 increases effective non-linearity while respecting state_size <= 32 constraint.
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
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
- Rationale: Directions explicitly encourage multi-stream GDN edits to push architecture hard without violating hard locks on state_size.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_1/n4/iter_003_dual_stream_gdn_n2

