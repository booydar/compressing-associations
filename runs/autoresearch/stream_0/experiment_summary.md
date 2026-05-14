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

## Iter 22 | failed | N=4
- Hypothesis: Adding a learnable temperature parameter to the reader's cross-attention replaces the fixed head_dim**-0.5 scaling, allowing the model to adaptively control how sharply it focuses on individual memory slots versus averaging across all M=4 slots during retrieval at N=4.
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: experiment error: Experiment script exited with code 1
--- train.log tail (/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp/train.log) ---
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
subprocess.CalledProcessError: Command '['/cephfs/home/bulatov/envs/gpu8/bin/python3.11', 'run_rmm_on_kv_retrieval-v5p1.py', '--exp_path', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp', '--per_device_batch_size', '64', '--gradient_accumulation_steps', '1', '--total_batch_size', '64', '--data_path', './data/N4-K2V2-V62_1M', '--tokenizer_path', './tokenizers/kv_alphabet_62/', '--learning_rate', '3e-4', '--n_layer', '4', '--n_head', '4', '--n_embd', '128', '--n_pairs', '4', '--n_keys', '2', '--n_values', '2', '--base_model', 'llama', '--fla_layer', 'GatedDeltaNet', '--state_size', '32', '--expand_v', '2.0', '--conv_kernel', '4', '--num_memory_vectors', '4', '--write_mode', 'cross_attn', '--read_mode', 'cross_attn', '--tokens_per_segment', '1', '--max_steps', '25000', '--eval_steps', '500', '--logging_steps', '500', '--warmup_steps', '10000', '--early_stopping_patience', '20', '--seed', '142']' returned non-zero exit status 1.
- Rationale: The reader achieves token_acc=0.5693 but EM=0.3194, meaning it retrieves some tokens correctly but struggles with simultaneous 4-pair retrieval. The fixed attention temperature (head_dim**-0.5 = 0.177 for head_dim=32) may be suboptimal — too sharp causes attention collapse onto 1-2 slots, too soft loses slot discrimination. A learnable log_temperature parameter lets the network discover the optimal attention distribution for each layer, adapting focus per-layer during training. This complements the reader FFN residual (iter_019) by improving the attention mechanism itself rather than just the post-attention transformation.
- exp_path: /cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp

## Iter 23 | failed | N=4
- Hypothesis: FAILED: executor failed after 4 attempts: The previous iteration's training run failed with the following error. Take this into account when applying the change; if your edit must avoid the same failure, adjust accordingly.

experiment error: Experiment script exited with code 1
--- train.log tail (/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp/train.log) ---
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
subprocess.CalledProcessError: Command '['/cephfs/home/bulatov/envs/gpu8/bin/python3.11', 'run_rmm_on_kv_retrieval-v5p1.py', '--exp_path', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp', '--per_device_batch_size', '64', '--gradient_accumulation_steps', '1', '--total_batch_size', '64', '--data_path', './data/N4-K2V2-V62_1M', '--tokenizer_path', './tokenizers/kv_alphabet_62/', '--learning_rate', '3e-4', '--n_layer', '4', '--n_head', '4', '--n_embd', '128', '--n_pairs', '4', '--n_keys', '2', '--n_values', '2', '--base_model', 'llama', '--fla_layer', 'GatedDeltaNet', '--state_size', '32', '--expand_v', '2.0', '--conv_kernel', '4', '--num_memory_vectors', '4', '--write_mode', 'cross_attn', '--read_mode', 'cross_attn', '--tokens_per_segment', '1', '--max_steps', '25000', '--eval_steps', '500', '--logging_steps', '500', '--warmup_steps', '10000', '--early_stopping_patience', '20', '--seed', '142']' returned non-zero exit status 1.
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: The previous iteration's training run failed with the following error. Take this into account when applying the change; if your edit must avoid the same failure, adjust accordingly.

experiment error: Experiment script exited with code 1
--- train.log tail (/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp/train.log) ---
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
subprocess.CalledProcessError: Command '['/cephfs/home/bulatov/envs/gpu8/bin/python3.11', 'run_rmm_on_kv_retrieval-v5p1.py', '--exp_path', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/n4/iter_022_reader_learnable_temp', '--per_device_batch_size', '64', '--gradient_accumulation_steps', '1', '--total_batch_size', '64', '--data_path', './data/N4-K2V2-V62_1M', '--tokenizer_path', './tokenizers/kv_alphabet_62/', '--learning_rate', '3e-4', '--n_layer', '4', '--n_head', '4', '--n_embd', '128', '--n_pairs', '4', '--n_keys', '2', '--n_values', '2', '--base_model', 'llama', '--fla_layer', 'GatedDeltaNet', '--state_size', '32', '--expand_v', '2.0', '--conv_kernel', '4', '--num_memory_vectors', '4', '--write_mode', 'cross_attn', '--read_mode', 'cross_attn', '--tokens_per_segment', '1', '--max_steps', '25000', '--eval_steps', '500', '--logging_steps', '500', '--warmup_steps', '10000', '--early_stopping_patience', '20', '--seed', '142']' returned non-zero exit status 1.
- Rationale: The reader achieves token_acc=0.5693 but EM=0.3194, meaning partial retrieval works but simultaneous 4-pair retrieval is limited. The LlamaCrossAttention value projection compresses 512-dim memory vectors to only num_heads(4)*head_dim(32)=128 total dims, a severe 4x compression. Doubling head_dim to 64 gives v_proj output of 256 dims (50% of memory width), providing richer attended information for the FFN residual (iter_019) to process. The o_proj then learns to compress 256->128 for the residual, but the attention mechanism itself operates with more information.
- exp_path: 

