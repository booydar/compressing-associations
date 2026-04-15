# Human Research Directions

**Instructions:**
1. Focus on changing hyperparameters first, architecture later. Start with changing dimension, number of layers/heads and training parameters.
2. If all you try does not work, it is possible to increase the number of iterations

Mark completed items as `[Done]`, skipped items as `[Skipped]`, failed attempts as `[Failed]`, and add new items with `[Pending]`.
The planner prioritizes the most recent untried `[Pending]` item.

## Priority Experiment Suggestions (ordered by implementation speed)

### Phase 1: Memory Initialization & State Capacity (Fastest Wins)

2. [Pending] **Memory token count sweep**
   Test `1, 4, 8, 16, 32, 64` memory tokens while matching total state capacity
3. [Pending] **Memory dimension reduction**
   Reduce memory dim to `0.5× / 0.25× hidden`, compensate with more tokens
4. [Pending] **Per-layer vs shared memory**
   Test sharing memory across last 2–4 layers
5. [Pending] **Single-head memory attention**
   Replace multi-head with single head for memory CA
8. [Pending] **Memory positional encoding ablation**
   Test no PE vs absolute vs relative
9. [Pending] **Delta rule for memory update**
   Replace CA write with: `Mem_new = Mem + (H - Mem) × gate`
10. [Pending] **Gated delta rule**
    Add input-dependent gating: `gate = σ(W_g × Mem, H)`
11. [Pending] **Forget gate**
    Add reset gate to clear old memories
12. [Pending] **Multi-stage write**
    Coarse selection + fine delta update
13. [Pending] **Segment-length curriculum**
    Start `segment_size = 64`, grow to `512`
14. [Pending] **Memory dropout**
    Randomly hide memory tokens (`p = 0.1–0.3`)
15. [Pending] **Deep supervision**
    Auxiliary loss at segment boundaries
16. [Pending] **Gradient clipping sweep**
    Test `clip_norm ∈ {0.1, 1.0, 5.0}`
17. [Pending] **RMCA-Delta**
    RMT read + GDN write
18. [Pending] **RMCA-Gated**
    Mamba-style SSM + attention read gate
19. [Pending] **RMCA-Hybrid**
    All components together

## Key Constraints

- Each experiment should complete in **< 2 hours** (configurable `max_steps`)

## Implementation History

- (none yet - all hyperparameter suggestions pending)