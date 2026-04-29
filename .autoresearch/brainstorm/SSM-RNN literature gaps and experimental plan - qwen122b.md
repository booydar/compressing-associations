# SSM/RNN literature gaps and experimental plan (fork #1)

**Session ID:** ses_297d5f46cffekKUBsRWeNmJljY
**Created:** 4/7/2026, 4:37:59 PM
**Updated:** 4/9/2026, 3:52:32 PM

---

## User

1. Missing Papers

Based on the extracted literature, you might want to consider:

- Jelassi et al. 2024 - Theoretical analysis of why SSMs underperform at copying (cited in Arora 2025)
- Merrill et al. 2024 - Expressivity gap between linear and non-linear RNNs (cited in M2RNN)
- Grazzi et al. 2024 - Eigenvalue constraints on SSMs for state tracking (cited in M2RNN)
- Siems et al. 2025 - Householder matrix parameterizations for expressivity (cited in M2RNN)
- xLSTM (Beck et al. 2024) - Another recent matrix-state RNN architecture

---

1. Which Points Have Been Addressed?

State Size (Component 1):

- Heavily addressed - M2RNN (2026) explicitly demonstrates that non-linear RNNs underperform primarily due to smaller state sizes, not non-linearity. Vector-valued states (RNN/GRU) vs matrix-valued states (Mamba2/GDN) is the key distinction.
- What's left: The papers show state size matters, but don't systematically compare effective state capacity across architectures at matched parameters. Your RMT work could explore this gap.
Write Mechanism (Component 2):
- Partially addressed - Yang et al. 2025 (Gated DeltaNet) shows gating + delta rule are complementary: gating enables rapid erasure, delta rule enables targeted updates. This directly addresses the "write mechanism" question.
- What's left: No systematic comparison of transplanting write mechanisms across architectures (e.g., adding delta rule to RMT, or gating to linear attention).
Input-Dependence / Selectivity (Component 3):
- Well addressed - Zoology (2312.pdf) and Mamba (Gu & Dao 2023) both identify input-dependent filters as critical. MqAR (multi-query associative recall) shows gated convolutions require dimension to scale with sequence length unless they have input-dependence.
- What's left: The papers show input-dependence helps, but don't explain why some architectures learn induction vs direct retrieval. Arora 2025 uses mechanistic interpretability to show this.
Depth:
- Not well addressed - Most papers use 2-layer models for synthetic tasks, or fixed depth for language modeling. No systematic study of how depth interacts with state size or write mechanism.

---

1. Tasks That Successfully Distinguish Models
  1. Most Discriminative Tasks:  
  Task	Distinguishes	Key Finding  
  MqAR (Zoology)	Attention vs. Gated Convs	Gated convs need d ≥ N for accuracy; attention needs constant d  
  Selective Copying (Mamba)	LTI vs. Selective SSMs	LTI models fail at ~57%; selective SSMs achieve ~99.8%  
  Induction Heads (Mamba)	Selective vs. Non-selective	Mamba extrapolates to 1M tokens; others fail at 2×  
  S-NIAH (GDN)	Delta rule vs. Gating	DeltaNet excels at retention; Mamba2 excels at filtering  
  S5 Permutation (M2RNN)	Linear vs. Non-linear	Linear RNNs cannot solve; M2RNN achieves 100%  
  ATR (Arora 2025)	Induction vs. Direct retrieval	Mechanistic analysis shows different mechanisms  
  Key Insight: Synthetic tasks alone are misleading. MqAR is better than single-query AR because it captures real language behavior. S-NIAH-2/3 (with real-world essays) is better than S-NIAH-1 (synthetic) for distinguishing memory management.

1. Results and What's Still Unanswered

Established Results:

1. Gated convolutions without input-dependence require O(N) dimension for MqAR (Zoology)
2. Selectivity enables Mamba to solve induction heads at 1M tokens (Mamba)
3. Matrix-valued states are necessary for strong language modeling in non-linear RNNs (M2RNN)
4. Gating + delta rule are complementary for memory management (GDN)
5. Short convolutions enable association in Mamba/Based (Arora 2025)

Still Unanswered:

1. Effective state capacity at matched parameters - M2RNN shows larger states help, but no cross-architecture comparison of state efficiency
2. Transplanting components - No paper systematically adds delta rule to RMT, or gating to other architectures
3. Why do some architectures learn induction vs direct retrieval? - Arora 2025 shows this empirically but doesn't explain the architectural determinants
4. Depth interaction - How does depth interact with state capacity and write mechanism?
5. RMT-specific analysis - Your RMT/ARMT work isn't in this literature. How does RMT's memory mechanism compare to SSMs?

---

Implications for Your Narrative
Your current narrative is partially addressed but has room:

1. State size is known to matter, but your angle could be effective capacity per parameter across different state representations (vector, matrix, memory tokens)
2. Write mechanism is partially understood (gating vs delta), but transplanting experiments are missing
3. RMT's role is not in this literature - this is a unique contribution opportunity

For ARR/NeurIPS timeline, the most viable path is:

- Focus on state capacity + write mechanism transplant experiments
- Use MqAR + S-NIAH-2/3 as discriminative tasks
- Show that adding delta rule or gating to weaker architectures improves them
- Position as "component surgery" paper rather than "Mamba is better" here is the literature review on the given topic. check out the notes, specifically todo in the obsidian db for the state of current experiments. Suggest the plan how can we create a publishable set of experiments starting from current point to cover the literature gaps provided above



...

## Research Plan: "Component Surgery in Recurrent Architectures"

### Core Contribution

**"State Capacity and Write Mechanisms in Recurrent Sequence Models: A Component-Wise Analysis"**

Position: Show that when matching state capacity and transplanting write mechanisms, the performance gaps between architectures narrow significantly, revealing that component design matters more than architecture family.

### Timeline Breakdown (4-6 weeks)

**Week 1: Foundation & Baselines**
**Week 2: State Capacity Experiments**  
**Week 3: Component Transplant Experiments**
**Week 4: Analysis & Writing**
**Weeks 5-6 (buffer): Extended experiments & submission**

---

### Experimental Design

#### Experiment 1: State Capacity Matching (Priority: High)

**Goal:** Match Mamba2/GDN (matrix states) with RMT/ARMT (vector states) by effective state size

**Setup:**

- Base models: RMT, ARMT, Mamba2-Base, GDN-Base
- Vary hidden dimension to match **effective state capacity**:
  - Mamba2: `state_size = n_heads * d_state` (matrix)
  - RMT: `mem_tokens * hidden_dim` (vector)
  - Match at 3 levels: 1K, 4K, 16K effective state parameters

**Tasks:**

1. **MqAR** (multi-query associative recall) - from Zoology
  - Vary key-value count: 32, 64, 128
  - Measure accuracy vs. state size scaling
2. **S-NIAH** (Needles In Haystack)
  - Use real-world essays version (S-NIAH-2/3)
  - Sequence lengths: 8K, 16K, 32K
3. **Selective Copying** (from Mamba paper)
  - Short vs. long sequences
  - Measure copying accuracy

**Expected Result:** Show that vector-state models can match matrix-state models when given equivalent state capacity, but with different scaling behavior.

---

#### Experiment 2: Write Mechanism Transplant (Priority: High)

**Goal:** Test if adding delta rule or gating improves weaker architectures

**Transplants:**

1. **RMT + Delta Rule** → Replace RMT's cross-attention write with GDN's delta update
2. **Mamba + Gating** → Add gating mechanism to Mamba2's SSM update
3. **Linear Attention + Selectivity** → Add Mamba-style input-dependent filtering

**Tasks:**

- **Associative Retrieval** (Phonebook task)
- **bAbI QA** (long-context version)
- **MqAR** (to test write precision)

**Expected Result:** Delta rule improves RMT on retention tasks; gating improves Mamba on filtering tasks.

---

#### Experiment 3: RMCA as Unified Framework (Priority: Medium)

**Goal:** Position RMCA as the architecture that combines best components

**Configuration Matrix:**


| Config      | Short-Term R/W | Long-Term R/W | Expected Strength  |
| ----------- | -------------- | ------------- | ------------------ |
| RMCA-Attn   | Cross-Attn     | Cross-Attn    | Information mixing |
| RMCA-Delta  | Cross-Attn     | Delta Rule    | Retention          |
| RMCA-Gated  | Cross-Attn     | Gated SSM     | Filtering          |
| RMCA-Hybrid | Cross-Attn     | Delta + Gate  | Balanced           |


**Tasks:**

- **Full benchmark suite** from Experiments 1-2
- **Language modeling** (small-scale, 100M params)
  - WikiText-2 or C4 subset
  - Compare perplexity at matched compute

**Expected Result:** Hybrid configuration matches or exceeds specialized architectures across tasks.

---

#### Experiment 4: Training Dynamics Analysis (Priority: Low, but valuable)

**Goal:** Explain WHY component choices affect training stability

**Analysis:**

1. **Gradient norm evolution** across training for each configuration
2. **Memory utilization** - how much of state capacity is actually used
3. **Overfitting curves** - recurrent vs. parallel architectures
4. **Curriculum effects** - when does skip connection "click"?

**Tasks:**

- Track same configurations from Experiment 3
- Use MqAR + Phonebook (faster to converge)

**Expected Result:** Delta rule enables faster convergence; gating reduces overfitting.

---

### Minimal Viable Paper Scope

If time runs short, focus on **Experiment 1 + 2 only**:

**Title:** "State Capacity and Write Mechanisms Explain Performance Gaps in Recurrent Sequence Models"

**Claims:**

1. State capacity mismatches explain part of the RMT vs. Mamba performance gap
2. Transplanting delta rule improves RMT on associative recall
3. Transplanting gating improves Mamba on selective copying
4. RMCA provides a unified framework for combining these components

**Tables Needed:**

- Table 1: State capacity matching results (MqAR, S-NIAH)
- Table 2: Component transplant results (before/after delta/gating)
- Table 3: RMCA configurations comparison
- Figure: Training dynamics (gradient norms, utilization)

---

### Implementation Plan

**Week 1 Tasks:**

```
Day 1-2: 
- Finalize Mamba2 + GDN codebase (fix tokenizer issues from TODO)
- Implement state capacity matching utility

Day 3-4:
- Set up MqAR evaluation (from Zoology code)
- Set up S-NIAH-2/3 evaluation

Day 5-7:
- Run baseline experiments (RMT, ARMT, Mamba2, GDN at matched params)
- Start state capacity scaling runs
```

**Week 2 Tasks:**

```
Day 8-10:
- Implement delta rule transplant for RMT
- Implement gating transplant for Mamba2

Day 11-14:
- Run transplant experiments
- Collect training dynamics metrics
```

**Week 3 Tasks:**

```
Day 15-18:
- Run RMCA configuration matrix
- Complete all benchmark evaluations

Day 19-21:
- Analysis: gradient norms, state utilization
- Create visualizations
```

**Week 4 Tasks:**

```
Day 22-25: Write paper (methods + results)
Day 26-28: Internal review + revision
Day 29-30: Final formatting + submission
```

---

### Resource Allocation

**With 8-32 GPUs and 1-2 students:**

- Student 1: Focus on Experiment 1 (state capacity) + baselines
- Student 2: Focus on Experiment 2 (transplants) + RMCA
- You: Oversight, Experiment 4 (analysis), paper writing

**Compute Budget Estimate:**

- Baseline runs: 4 GPU-days per model configuration
- State capacity scaling: 12 GPU-days (3 sizes × 4 models)
- Transplant experiments: 8 GPU-days (2 transplants × 4 tasks)
- RMCA matrix: 16 GPU-days (4 configs × 4 tasks)
- **Total: ~40 GPU-days** (feasible on 8 GPUs in 5 days)

---

### Risk Mitigation

**Risk 1:** Mamba2/GDN code not ready

- **Mitigation:** Start with RMT + ARMT only; add SSM baselines later

**Risk 2:** Transplant experiments fail

- **Mitigation:** Focus on state capacity results (Experiment 1) as primary contribution

**Risk 3:** Time runs out

- **Mitigation:** Submit as short paper/letter focusing on Experiment 1 only

---

### Questions for You

1. **Codebase readiness:** Is the RMCA codebase ready for the component transplant experiments, or does it need cleanup first?
2. **Datasets:** Do you have MqAR and S-NIAH-2/3 evaluation code ready, or does this need to be implemented?
3. **Model checkpoints:** Do you have pretrained RMT/ARMT checkpoints, or do we need to train from scratch?
4. **Priority:** If we can only complete 2 experiments, should it be (1) State Capacity + (2) Transplants, or (1) State Capacity + (3) RMCA framework?

---

## User

need a plan for autoresearch that will iterate over ideas for RMCA - how to improve it / make it work etc. based on this research plan, formulate suggestions for autoresearch as bullet points. they should be described precicely enough to be completed by average model. these ideas should be targeted at our discussed research direction; should not make experiments too long; have to cover as much simple improvements as possible; coverage of these ideas have to help move to our research goals discussed above.

---

## Assistant (Plan · unsloth/Qwen3.5-122B-A10B-GGUF-Q3 · 132.7s)

*Thinking:*

The user wants me to create an autoresearch plan that will iterate over RMCA improvement ideas. This should be:

1. Precise enough for an average LLM to complete
2. Targeted at our research direction (state capacity + component transplant + RMCA framework)
3. Not make experiments too long
4. Cover simple improvements
5. Help move toward our research goals

I need to formulate this as a plan (not execute yet) with bullet points describing specific ideas for autoresearch to iterate on.

Let me think about what specific, concrete improvements could be tested for RMCA:

1. Memory initialization strategies (Hippo vs random vs learned)
2. Cross-attention variants (single head vs multi-head, linear vs softmax)
3. Gate mechanisms (learnable vs sigmoid vs hard)
4. Skip connection patterns
5. Layer normalization placements
6. Memory update frequencies
7. Read/write objective combinations
8. State capacity matching techniques
9. Delta rule integration
10. Gating integration

Each idea should be:

- Self-contained (can be tested independently)
- Fast to implement (1-2 hours)
- Fast to evaluate (quick training on synthetic tasks)
- Measurable (clear metric for improvement)

Let me create a structured autoresearch plan with these ideas.

## Autoresearch Plan for RMCA Improvement Iteration

Based on the research plan, here's a structured autoresearch iteration framework with precise, actionable ideas:

---

### Autoresearch Loop Structure

```
For each idea:
1. Implement (max 2 hours)
2. Run on MqAR-32 + Phonebook-100 (fast convergence)
3. Compare to baseline (accuracy + training stability)
4. Keep if improvement > 2% or stability gain
5. Document findings for paper
```

---

### Priority 1: Memory Initialization & State Capacity (Week 1)

**Idea 1.1: Initialize memory with Hippo distribution**

- Replace random memory initialization with S4/Hippo initialization
- Use `A = -λI + noise` where λ ∈ [0.5, 2.0]
- Test: RMT vs. Hippo-initialized RMT on MqAR-32

**Idea 1.2: Memory token count scaling**

- Test memory tokens: 1, 4, 8, 16 per segment
- Match total state size to Mamba2's d_state × n_heads
- Measure: accuracy vs. token count tradeoff

**Idea 1.3: Per-layer vs. shared memory**

- Baseline: Each layer has own memory (current RMCA)
- Variant: Share memory across last 2-4 layers
- Measure: parameter efficiency + performance

**Idea 1.4: Memory dimension reduction**

- Keep memory at 0.5×, 0.25× hidden_dim
- Compensate with more memory tokens
- Test: Can we reduce memory params without losing performance?

---

### Priority 2: Cross-Attention Variants (Week 1-2)

**Idea 2.1: Single-head memory attention**

- Replace multi-head with single head for memory cross-attention
- Rationale: memory may not need full head diversity
- Measure: compute savings vs. accuracy drop

**Idea 2.2: Linear memory attention**

- Replace softmax with linear attention in memory read
- Use per-token recurrence instead of full attention
- Test: Training stability + extrapolation to longer sequences

**Idea 2.3: Sigmoidal attention for dense writes**

- Replace softmax with sigmoid (λ × sigmoid(λ × scores))
- Allow multiple tokens to write to same memory vector
- Measure: memory utilization rate + AR accuracy

**Idea 2.4: Residual memory stream**

- Add skip connection: `Mem_next = Mem_old + ΔMem`
- Compare to current: `Mem_next = ΔMem` (replace)
- Test: Long-term retention on S-NIAH-16K

---

### Priority 3: Write Mechanism Transplants (Week 2)

**Idea 3.1: Delta rule for memory update**

- Replace: `Mem_new = CrossAttn(Mem, H)`
- With: `Mem_new = Mem + (H - Mem) × gate` (delta rule)
- Gate: learned scalar or input-dependent
- Test: MqAR accuracy + convergence speed

**Idea 3.2: Gated delta rule (GDN-style)**

- Add input-dependent gating to delta rule
- `gate = σ(W_g × [Mem, H])`
- Separate gates for read/write
- Measure: selective copying performance

**Idea 3.3: Householder parameterization**

- Parameterize memory update as product of Householder matrices
- Use k=2-4 Householder reflections for expressivity
- Test: State tracking tasks (permutation)

**Idea 3.4: Multi-stage write**

- Write in 2 stages: coarse (attention) + fine (delta)
- Stage 1: Select which memory slots to update
- Stage 2: Apply delta updates to selected slots
- Measure: Write precision on MqAR

---

### Priority 4: Gating & Selectivity (Week 2-3)

**Idea 4.1: Input-dependent read gate**

- Add gate: `read = σ(W × [query, memory])`
- Control when to read from memory
- Test: Filtering performance on selective copying

**Idea 4.2: Memory reset gate**

- Add gate to clear old memories: `Mem = reset × Mem`
- Reset signal: learned or based on surprise metric
- Test: S-NIAH with multiple needles (forget old)

**Idea 4.3: Selective memory update**

- Only update memory when error > threshold
- Use reconstruction loss as surprise signal
- Measure: Training efficiency + final performance

**Idea 4.4: Layer-wise selectivity**

- Some layers: attention-only, no memory
- Other layers: memory-heavy, no self-attention
- Pattern: alternating or learned mask
- Test: Parameter efficiency + performance

---

### Priority 5: Training Stability & Curriculum (Week 3)

**Idea 5.1: Segment-length curriculum**

- Start: segment_size=64, gradually increase to 512
- Compare: fixed vs. curriculum training
- Measure: Final accuracy + convergence iterations

**Idea 5.2: Memory dropout**

- Randomly hide memory tokens during training (p=0.1-0.3)
- Force model to rely on short-term context
- Test: Generalization to unseen sequence lengths

**Idea 5.3: Deep supervision**

- Add auxiliary loss at each segment boundary
- Predict next segment start from current memory
- Measure: Memory formation quality

**Idea 5.4: Gradient clipping strategies**

- Test: global norm clipping vs. per-layer vs. no clipping
- Vary: clip_norm ∈ [0.1, 1.0, 5.0]
- Measure: Training stability (failure rate)

---

### Priority 6: Hybrid Configurations (Week 3-4)

**Idea 6.1: RMCA-Delta (RMT + delta rule)**

- Combine: RMT cross-attention read + GDN delta write
- Test: Full benchmark suite if promising
- Position: "Best of both worlds" for retention

**Idea 6.2: RMCA-Gated (Mamba + attention)**

- Combine: Mamba2 SSM + cross-attention read gate
- Test: Selective copying + AR tasks
- Position: Improved filtering for SSMs

**Idea 6.3: RMCA-Hybrid (attention + delta + gate)**

- All three components together
- Use learned gating to choose between update modes
- Test: Main contribution configuration

**Idea 6.4: RMCA-Linear (linear attention + delta)**

- Replace all attention with linear
- Keep delta rule for memory update
- Test: Extrapolation + compute efficiency

---

### Fast Evaluation Protocol

**For each idea, run this minimal test:**

```
Task: MqAR-32 (32 key-value pairs)
Model: 50M params (small enough for fast iteration)
Batch: 32, Seq: 512
Training: 5K steps (should see convergence)
Metric: Exact match accuracy
Success: >2% improvement or 2× faster convergence
```

**If Idea passes minimal test, expand to:**

```
Tasks: MqAR-64, Phonebook-100, Selective Copying
Training: 20K steps
Measure: Full accuracy + training dynamics
```

---

### Documentation Template for Each Idea

```markdown
## Idea: [Name]

**Hypothesis:** [1-2 sentences]
**Implementation:** [Key changes to RMCA]
**Baseline:** [Which RMCA version]
**Result:** [Accuracy, training steps, stability]
**Verdict:** [Keep/Discard/Modify]
**Paper relevance:** [State capacity / Write mechanism / Training dynamics]
```

---

### Expected Outcomes & Paper Mapping


| Experiment Category         | Paper Section        | Expected Contribution             |
| --------------------------- | -------------------- | --------------------------------- |
| Memory Initialization       | Methods + Appendix   | State capacity matching technique |
| Cross-Attention Variants    | Methods              | RMCA architectural choices        |
| Write Mechanism Transplants | Results + Discussion | Component transplant findings     |
| Gating & Selectivity        | Results              | Why selectivity matters           |
| Training Stability          | Appendix             | Training recipe                   |
| Hybrid Configurations       | Main Results         | RMCA-Hybrid as contribution       |


---

### Autoresearch Agent Instructions

**For each iteration:**

1. Read current RMCA codebase
2. Pick next idea from priority list
3. Implement change (max 2 hours of code)
4. Run minimal test (MqAR-32, 5K steps)
5. Log results to experiment tracker
6. If successful, expand to full benchmark
7. Update documentation with findings
8. Move to next idea

**Stopping criteria:**

- Complete all Priority 1-3 ideas
- OR 3 consecutive failed ideas
- OR 2 weeks elapsed
- THEN compile results for paper

---

### Questions for You Before Implementation

1. **Codebase structure:** Is RMCA implemented as a single file or modular components? (affects implementation speed)
2. **Existing utilities:** Do you already have MqAR/Phonebook dataloaders and evaluation scripts?
3. **GPU time per iteration:** With 8-32 GPUs, how many parallel runs can we do? (affects total timeline)
4. **Student availability:** Can students run the autoresearch loop, or should this be fully automated?
5. **Priority order:** Should we start with state capacity (Priority 1) or write mechanisms (Priority 2)?

---

