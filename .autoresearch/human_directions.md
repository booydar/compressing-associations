# Human Research Directions

**Instructions:** 
!!!
Focus on changing HYPERPARAMETERS FIRST, architecture later. 
Start with changing dimension, number of layers/heads and training parameters. 
!!!

## Pending Suggestions

1. [PENDING] Try increasing n_mem_tokens from 8 to 16 or 32 - more memory capacity may help associative retrieval
2. [PENDING] Try increasing n_layer from 4 to 6 or 8 - more layers may improve pattern learning
3. [PENDING] Try learning rate sweep: 1e-4, 5e-4, 1e-3, 5e-3
4. [PENDING] Try increasing n_head from 4 to 8 or 16 for better multi-aspect attention
5. [PENDING] Try increasing n_embd from 128 to 256
6. [PENDING] Try different optimizers: AdamW, SGD with momentum
7. [PENDING] Try batch size variations: 32, 128, 256
8. [PENDING] Try longer training: 50000, 100000 steps
9. [PENDING] Try weight decay: 0.01, 0.1
10. [PENDING] Try different warmup ratios: 0.05, 0.1, 0.2

## Implementation History

- (none yet - all hyperparameter suggestions pending)
