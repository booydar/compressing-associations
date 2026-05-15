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

## Iter 28 | failed | N=4
- Hypothesis: FAILED: executor failed after 4 attempts: None
- Target: modeling_rmt/huggingface_rmm_v5p1.py
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: executor failed after 4 attempts: None
- Rationale: The current reader FFN uses a fixed residual (iter 19, EM=0.3194). A fixed addition forces equal reliance on both paths. A learnable gate initialized at 0.5 lets the network discover optimal weighting per position, potentially retrieving all 4 KV pairs more consistently.
- exp_path: 

## Iter 35 | failed | N=4
- Hypothesis: FAILED: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/artifacts/iter_035/planner_prompt.txt']' timed out after 900 seconds
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: planner failed after 2 attempts: planner failed after 2 attempts: Command '['opencode', 'run', '-m', 'llama_local/unsloth/Qwen3.5-122B-A10B-GGUF', 'Follow the research instructions in the attached file exactly.', '-f', '/cephfs/home/bulatov/2026/autoresearch/compressing-associations-gdn/runs/autoresearch/stream_0/artifacts/iter_035/planner_prompt.txt']' timed out after 900 seconds
- Rationale: (none)
- exp_path: 

## Iter 36 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 37 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 38 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 39 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 40 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 41 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 42 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 43 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 44 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 45 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 46 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 47 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 48 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 49 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 50 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 51 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 52 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 53 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 54 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 55 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 56 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 57 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 58 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 59 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 60 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 61 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 62 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 63 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 64 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 65 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 66 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 67 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 68 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 69 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 70 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 71 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 72 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 73 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 74 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 75 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 76 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 77 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 78 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 79 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 80 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 81 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 82 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 83 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 84 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 85 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 86 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 87 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 88 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 89 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 90 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 91 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 92 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 93 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 94 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 95 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 96 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 97 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 98 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 99 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 100 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 101 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 102 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 103 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 104 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 105 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 106 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 107 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 108 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 109 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 110 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 111 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 112 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 113 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 114 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 115 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 116 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 117 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 118 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 119 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 120 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 121 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 122 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 123 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 124 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 125 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 126 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 127 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 128 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 129 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 130 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 131 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 132 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 133 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 134 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 135 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 136 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 137 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 138 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 139 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 140 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 141 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 142 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 143 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 144 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 145 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 146 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 147 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 148 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 149 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 150 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 151 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 152 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 153 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 154 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 155 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 156 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 157 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 158 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 159 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 160 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 161 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 162 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 163 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 164 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 165 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 166 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 167 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 168 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 169 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 170 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 171 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 172 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 173 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 174 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 175 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 176 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 177 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 178 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 179 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 180 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 181 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 182 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 183 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 184 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 185 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 186 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 187 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 188 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 189 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 190 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 191 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 192 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 193 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 194 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 195 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 196 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 197 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 198 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 199 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 200 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 201 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 202 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 203 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 204 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 205 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 206 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 207 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 208 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

## Iter 209 | failed | N=4
- Hypothesis: FAILED: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Target: (none)
- EM: n/a
- Success: No model improvement established.
- Weaknesses: The experiment did not reach a valid kept result.
- Failures: unhandled: Expecting ',' delimiter: line 8 column 223 (char 1154)
- Rationale: (none)
- exp_path: 

