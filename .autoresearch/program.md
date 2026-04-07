# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMCA.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Model file: modeling_rmt/huggingface_rmca_v3.py
- No parameter count explosion (justify any increase)
- Max experiment length: 5000 steps
- Base config: L=4, H=4, D=128, llama backbone, BS=64, LR=3e-4

## Current State
- N-level: 2
- Current best EM: 0.0 (baseline not yet run)
- Best variant: none

## Task Format
The associative retrieval task: N key-value pairs are encoded in a context segment,
then a query key is given and the model must produce the matching value exactly.
- N=2: 2 pairs per context, single segment
- N=4: 4 pairs per context, single segment
- Each key is 2 chars, each value is 2 chars (K=2, V=2)
- Alphabet: 62 characters

## Model Architecture (RMCA v3)
Recurrent Memory with Cross-Attention (RMCA):
- Each transformer layer is wrapped with MemoryAugmentedLayer
- Each MemoryAugmentedLayer has:
  - memory_read: cross-attention from hidden_states → memory
  - memory_write: cross-attention from memory → hidden_states
  - LayerNorms: memory_layer_norm, input_layer_norm (RMSNorm)
  - Memory state: per-layer, shape (batch, num_mem_tokens, hidden_size)
- Memory is reset after each forward pass (per-sample, no BPTT across samples)

## Current Understanding
(updated each iteration by autoresearch loop)
