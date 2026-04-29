# RMCA architecture notes review obsidian-db

**Session ID:** ses_2cbffcad0ffeEYNuWp3LDeIg9J
**Created:** 3/28/2026, 1:32:02 PM
**Updated:** 3/28/2026, 2:50:13 PM

---

## User

RN i'm working on this RMCA architecture. The notes on research, todo etc are stored in the ./obsidian-db folder in this directory. Find all the relevant info in my notes that u can find, the idea of the method, the objectives and the current state -- how its performing, whats on the agenda and current limitations/directions for the future.

---

## **...**

## Assistant (Plan · qwen_qwen3.5-27b@iq4_xs · 32.8s)

Based on my analysis of your notes, here's a comprehensive summary of the RMCA architecture:

## **RMCA (Recurrent Memory Cross-Attention)**

### Core Idea & Objectives

**Goal:** Create a unified recurrent memory architecture that generalizes RMT, ARMT, and Mamba/Gated DeltaNet under a single framework. The main objective is to make training for recurrent models easier and more effective by separating parameters for memory operations and making them act on each token individually.

**Key Insight:** RMCA interpolates between different architectures by varying the number of tokens selected for cross-attention (from per-token Mamba-like behavior to full-segment ARMT-like behavior). If cross-attention is linear, it becomes ARMT; it can also be configured as Mamba/RWKV.

### Architecture Design

**Memory Structure:**

- Memory initialized as a matrix per layer: `n_mem × hidden_dim`
- Memory stays in its layer → horizontal memory residual stream
- Read/write performed via T5-style cross-attention layers

**RMCA Layer Operations:**

```
(H, Mem) - layer L
H_L-tmp ← H_L-1 + CrossAttention(LN(H_L-1), LN(Mem_L))  [Read]
H_L ← H_L-tmp + TransformerBlock(LN(H_L-tmp))

Mem_L-next ← Mem_L + CrossAttention(LN(write), LN(H_L-1))  [Write]
```

**Variants (V0-V4):** Different memory update strategies using cross-attention with varying inputs.

### Current State & Performance

**Status:** Active development (Feb-Mar 2026)

- Working draft completed (mid-Feb 2026)
- Running ablation experiments on memory initialization, gate removal, cross-attention variants
- Comparison framework against GDN/Mamba/RMT baselines in place

**Key Findings:**

- RMCA uses **two memory types**: short-term and long-term
- Short-term: Self-Attention (S-A) for both read/write
- Long-term: Cross-Attention (C-A) for both read/write
- Hypothesis: "Double attention is hard to train with recurrence"

### Current Agenda & Limitations

**Immediate Tasks:**

1. Learning rate tuning for RMCA
2. Tokenizer fixes for Mamba/RWKV baselines
3. Multi-layer experiments, FF layers, gating mechanisms
4. Memory initialization strategies (Hippo/S4 vs random)
5. Benchmark on PhoneBook, Associative Retrieval tasks

**Core Problems Being Investigated:**

- **Q0:** What is the core problem of RMCA / segment-level recurrence?
- **Q1:** How to simplify the aggregating function?
- Training instability even with curriculum learning
- Limited memory capacity compared to Mamba/GDN on some tasks

**Future Directions:**

1. Replace attention with gates for discrete choices (gates better than attention for read/write)
2. LSTM-based memory state updates
3. Sigmoidal attention for dense writes (more tokens per memory vector)
4. Hierarchical models with both short- and long-term memory types

**Target Venues:** ARR → ACL/EMNLP 2027 or ICML 2027, NeurIPS 2026 workshop

---

## User

provide a comprehensive analysis: idea (novelty, impact, formalization), architecture (adequacy, component efficiency), experimental approach (adequacy, datasets, baselines) and overall high-level comments. Then suggest improvements on all of these topics

---

## Assistant (Plan · qwen_qwen3.5-27b@iq4_xs · 630.8s)

*Thinking:*

The user wants a comprehensive analysis of RMCA across multiple dimensions and suggestions for improvements. I need to synthesize all the information I've gathered from their notes into a structured critique covering idea, architecture, experimental approach, and high-level comments, then provide concrete improvement suggestions for each area.

# Comprehensive Analysis of RMCA Architecture

## 1. IDEA ANALYSIS

### Novelty Assessment

**Strengths:**

- **Unified framework concept**: The interpolation between Mamba (per-token) ↔ ARMT (full-segment) via configurable token selection is genuinely novel. This creates a continuous spectrum rather than discrete architecture choices.
- **Hierarchical memory types**: Separating short-term (self-attention) from long-term (cross-attention) memory addresses a gap in existing recurrent models that typically use one mechanism for all timescales.
- **Operation-specialization hypothesis**: "Gates for discrete choices, attention for information mixing" is an underexplored principle with theoretical grounding potential.

**Weaknesses:**

- The core cross-attention + recurrence combination isn't entirely new (see: Memory Networks, Neural Turing Machines, Transformers with memory). What's novel is the *segment-level* formulation and unification claim.
- The "generalization" claim needs formal proof: Is RMCA truly a superset of Mamba/RMT/ARMT, or just architecturally similar?

**Novelty Score:** 7/10 - Strong conceptual framing, but core mechanisms have precedents.

### Impact Potential

**High-Impact Angles:**

- **Training recipe for recurrent models**: If RMCA solves the "hard to train" problem (T1 in your notes), this is broadly impactful beyond the architecture itself.
- **Long-context pretraining at scale**: Directly addresses P1-P3 (memory, efficiency, expressivity) which are industry pain points.
- **Theoretical unification**: A common framework for Transformer/SSM/RMT could reshape how we think about sequence models.

**Limitations:**

- Impact depends entirely on empirical validation. Without clear wins over Mamba2/GDN/Transformer-XL, it's an academic curiosity.
- The "unified" claim may dilute the narrative: reviewers might prefer a focused contribution (e.g., "better training for recurrent models") over a broad unification story.

**Impact Score:** 8/10 if results validate claims; 4/10 otherwise.

### Formalization Quality

**Current State:**

- Layer equations are clear but informal (no notation for dimensions, attention variants)
- No formal definition of the "interpolation parameter" (n tokens selected)
- Missing: expressivity bounds, computational complexity analysis, relation to SSM differential equation form

**Gaps:**

1. **No theorem**: What can RMCA compute that others cannot? (or vice versa?)
2. **Parameter counting**: How does RMCA(n) scale with n? When does it become equivalent to Mamba vs ARMT?
3. **Gradient flow analysis**: Why should this be easier to train? No mechanistic explanation yet.

**Formalization Score:** 4/10 - Intuitive but lacks mathematical rigor.

---

## 2. ARCHITECTURE ANALYSIS

### Adequacy

**Design Strengths:**

- **Modular variants (V0-V4)**: Good ablation-friendly design that isolates memory update mechanisms.
- **Horizontal residual stream**: Preserves information flow, aligns with modern transformer practices.
- **Separate read/write paths**: Allows asymmetric optimization (e.g., cheap reads, expensive writes).

**Design Concerns:**

1. **"Double attention is hard to train" hypothesis** (from 2026-03-23 notes):
  - This is a *problem*, not a feature. If RMCA's core mechanism (cross-attention for both read/write) is inherently unstable, the architecture may be fundamentally flawed.
  - **Question**: Why not use attention only for reading and gates/linear ops for writing?
2. **Memory capacity vs. Mamba/GDN**:
  - Your notes admit RMCA's memory mechanism is "worse than mamba/gdn on some tasks" (Research Directions 03.2026).
  - This suggests the cross-attention bottleneck may be limiting factor.
3. **Positional encoding ambiguity**:
  - Do memory tokens need PE? Your notes mention this as an ablation but no conclusion yet.
  - Without clear positioning, how does RMCA handle order-sensitive tasks?

**Adequacy Score:** 6/10 - Well-structured but has unresolved design tensions.

### Component Efficiency


| Component               | Concern                                                  | Status                    |
| ----------------------- | -------------------------------------------------------- | ------------------------- |
| Cross-Attention (read)  | O(segment²) within segment; may bottleneck long contexts | Not optimized             |
| Cross-Attention (write) | Same as above; also writes are less critical than reads  | Overkill?                 |
| Transformer Block       | Standard; adds O(hidden²) per layer                      | Acceptable                |
| Memory Matrix           | n_mem × hidden_dim per layer; scales with depth          | Manageable if n_mem small |


**Efficiency Issues:**

1. **No linear attention variant**: Your notes mention this as a future direction, but it's critical for scaling. Without it, RMCA can't compete with Mamba/RWKV on long sequences.
2. **Memory update frequency**: Notes suggest "once per segment" but unclear if this is optimal. More frequent updates may help training stability.
3. **No sparsity mechanism**: Unlike Mamba's selective scan, RMCA processes all memory tokens equally.

**Efficiency Score:** 5/10 - Not competitive with SSMs without linearization.

---

## 3. EXPERIMENTAL APPROACH ANALYSIS

### Adequacy of Current Plan

**Strengths:**

- **Clear baselines**: Mamba, GDN, RMT, ARMT are all relevant and well-chosen.
- **Task diversity**: Associative Retrieval (AR), bAbI, PhoneBook cover different aspects (memorization, reasoning, structured data).
- **Ablation framework**: V0-V4 variants + initialization studies provide mechanistic insights.

**Critical Gaps:**

1. **No scaling laws**: Experiments seem focused on small models/tasks. Without demonstrating how RMCA scales to 1B+ parameters and 100K+ context, the "long-context" claim is unvalidated.
2. **Missing downstream NLP tasks**: Your GradMem notes mention filling "Table 2 gaps (complete NLP evaluation)" - same issue likely exists for RMCA. How does it perform on translation, summarization, QA?
3. **Training dynamics not measured**: You identify "hard to train" as a core problem but don't see planned experiments measuring: convergence speed, curriculum sensitivity, gradient norms, etc.

**Adequacy Score:** 6/10 - Good foundation but incomplete for A* venue.

### Datasets


| Dataset                    | Purpose                 | Adequacy                         |
| -------------------------- | ----------------------- | -------------------------------- |
| Associative Retrieval (AR) | KV retrieval benchmark  | ✅ Standard for memory models     |
| bAbI (QA1/QA2)             | Multi-hop reasoning     | ⚠️ Small, may not scale insights |
| PhoneBook                  | Structured memorization | ✅ Good for exact recall          |
| BABILong                   | Long-context reasoning  | ✅ Relevant but needs more tasks  |


**Missing:**

- **Real-world long-context datasets**: Need evaluation on actual documents (e.g., Qasper, MuSiQue, Needle-In-Haystack variants).
- **Perplexity benchmarks**: How does RMCA perform as a language model? (WikiText2, PTB)
- **Stress tests for recurrence**: Group multiplication (RWKV-style), parity tasks that expose recurrent vs parallel differences.

### Baselines

**Included:** Mamba, GDN, RMT, ARMT ✅

**Missing Critical Baselines:**

1. **Linear Attention models**: Performer, Linear Transformer - direct competitors if RMCA is linearized.
2. **Hybrid models**: Longformer, BigBird (sparse attention + recurrence).
3. **Recent SSMs**: DeltaNet variants, H3, Mamba2 with different state sizes.
4. **Retrieval-augmented models**: RETRO, Atlas - for comparison on memory tasks.

**Baseline Score:** 6/10 - Good core set but missing modern competitors.

---

## 4. HIGH-LEVEL COMMENTS

### Narrative Coherence

**Current Story:** "RMCA unifies RMT, ARMT, and Mamba under one framework with better training dynamics."

**Problems:**

1. **Too broad**: Unification + training improvements + hierarchical memory = three papers worth of claims.
2. **Unclear primary contribution**: Is it the architecture? The training recipe? The theoretical insight?
3. **"Double attention" instability**: This undermines the core mechanism unless resolved.

**Recommended Refinement:** Focus on ONE angle:

- Option A: "Hierarchical Memory for Recurrent Models" (short-term + long-term separation)
- Option B: "Training Recipes for Segment-Level Recurrence" (curriculum, initialization, gating)
- Option C: "Linear RMCA: Efficient Long-Context Modeling" (if linearization works well)

### Reviewer Anticipation

**Likely Criticisms:**

1. "Why not just use Mamba2 + LoRA for memory?" (simpler baseline)
2. "The unification claim is hand-wavy; where's the formal proof?"
3. "Results don't scale beyond toy tasks."
4. "Training instability makes this impractical."

**Pre-emptive Responses Needed:**

- Clear equivalence proofs for RMCA(n=Mamba_params) ≈ Mamba
- Scaling experiments on at least one realistic task (10K+ tokens)
- Training stability analysis with/without curriculum, different initializations

---

## 5. RECOMMENDED IMPROVEMENTS

### Idea-Level Improvements

**1. Sharpen the Novelty Claim**

```
Current: "RMCA generalizes RMT, ARMT, Mamba"
Better: "RMCA identifies a continuous spectrum between token-level 
         and segment-level recurrence, with n (tokens per attention) 
         as the interpolation parameter."
```

**2. Add Theoretical Component**

- Prove expressivity bounds: Show RMCA can simulate any SSM given sufficient memory tokens.
- Derive gradient flow equations: Explain why/when training is stable vs unstable.
- Complexity analysis: O(n_mem × segment_length) vs Mamba's O(segment_length).

**3. Reframe Around a Specific Problem**
Instead of "unified architecture," frame as:

> "Recurrent models fail at hierarchical memory: they either forget long-term 
> dependencies (RNNs) or overfit quickly (segment-level RMT). RMCA solves this 
> by separating short-term (self-attention) and long-term (cross-attention) memory."

### Architecture Improvements

**1. Replace Write Attention with Gating**

```python
# Current (unstable):
Mem_next = Mem + CrossAttention(LN(write), LN(H_prev))

# Proposed (more stable):
gate = sigmoid(Linear(H_prev))  # [batch, segment, n_mem]
write_vector = Linear(H_prev)   # [batch, segment, hidden]
Mem_next = Mem * (1 - gate) + write_vector * gate
```

**Rationale:** Your notes say "gates for discrete choices" - writing is a choice of what to store.

**2. Add Linear Attention Variant**

- Implement FlashAttention-style linear cross-attention for O(1) memory access.
- This makes RMCA competitive with Mamba on long sequences.

**3. Memory Positional Encoding Strategy**

```python
# Option A: No PE (memory is order-independent pool)
# Option B: Absolute PE from segment start (memory has temporal structure)
# Option C: Relative PE between memory tokens (learned relationships)

# Recommendation: Start with Option A, ablate to B/C if needed.
```

**4. Adaptive Memory Allocation**

- Instead of fixed n_mem, use learnable routing to allocate memory tokens dynamically.
- Inspired by MoE: some segments need more memory than others.

### Experimental Improvements

**1. Add Scaling Experiments**


| Model Size | Context Length | Task       | Metric   |
| ---------- | -------------- | ---------- | -------- |
| 50M        | 4K             | AR (N=100) | EM score |
| 200M       | 16K            | PhoneBook  | Recall@k |
| 1B         | 64K            | Qasper QA  | F1       |


**2. Training Dynamics Study**

- Measure: convergence epochs, gradient norm evolution, loss curve smoothness.
- Compare: RMCA vs Mamba vs RMT with identical hyperparameters.
- Analyze: When does curriculum help/hurt? What initialization works best?

**3. Downstream Transfer Tasks**

- Fine-tune on: translation (WMT), summarization (CNN/DailyMail), QA (SQuAD).
- Measure: Does RMCA's memory help with in-context learning?

**4. Ablation Priority Order**

1. **Critical**: Attention vs gating for write operation
2. **High**: Linear attention variant
3. **Medium**: Memory size scaling (n_mem = 8, 16, 32, 64)
4. **Low**: Positional encoding variants

### Baseline Improvements

**Add These Models:**

1. **Mamba2-1.3B** with same hidden dim as RMCA for fair comparison
2. **RWKV-6** (token-level recurrence baseline)
3. **Compressive Transformer** (explicit memory compression)
4. **Longformer** (sparse attention + local window)

**Matching Protocol:**

- Match by *state size* not parameter count: GDN/RWKV have matrix states, RMCA has memory matrix. Compare at equivalent state dimensions.
- Use same tokenizer across all models to eliminate tokenization artifacts.

### Narrative Improvements

**Recommended Paper Structure:**

```
Title: "Hierarchical Memory for Efficient Long-Context Modeling"

Abstract:
- Problem: Recurrent models struggle with hierarchical timescales
- Solution: RMCA separates short-term (self-attn) and long-term (cross-attn) memory
- Results: X% improvement on AR, Y% faster convergence than RMT, Z% less params than Mamba

Sections:
1. Introduction (motivate hierarchical memory need)
2. Related Work (RMT, Mamba, SSMs - position RMCA clearly)
3. Method (RMCA architecture + theoretical insights)
4. Experiments (AR tasks + scaling + training dynamics)
5. Analysis (when does each memory type matter?)
6. Conclusion
```

**Key Message:** Not "unified framework" but "hierarchical memory solves recurrent model limitations."

---

## 6. PRIORITY ACTION ITEMS

### Immediate (Next 2 Weeks)

1. **Fix write operation**: Implement gating variant, compare stability vs attention.
2. **Add linear attention**: Make RMCA scalable to long contexts.
3. **Run training dynamics study**: Measure convergence, gradient norms, curriculum effects.

### Short-Term (1 Month)

1. **Scaling experiments**: Test on 1B+ model with 64K context.
2. **Downstream tasks**: Evaluate on real NLP benchmarks.
3. **Formalize equivalence**: Prove RMCA(n) → Mamba/ARMT limits.

### Medium-Term (2-3 Months)

1. **Complete ablation suite**: All V0-V4 variants + initializations.
2. **Write paper draft**: Focus on hierarchical memory narrative.
3. **Submit to ARR**: Target ACL/EMNLP 2027 or NeurIPS 2026 workshop.

---

## Summary Assessment


| Dimension             | Score               | Verdict                                     |
| --------------------- | ------------------- | ------------------------------------------- |
| Novelty               | 7/10                | Strong framing, needs formal grounding      |
| Impact Potential      | 8/10 (if validated) | High if training stability solved           |
| Architecture Adequacy | 6/10                | Good structure, write mechanism problematic |
| Experimental Rigor    | 6/10                | Solid baseline, missing scaling/downstream  |
| Narrative Clarity     | 5/10                | Too broad, needs focus                      |


**Overall Recommendation:** RMCA has strong potential but requires: (1) fixing the write operation instability, (2) adding linear attention for scalability, and (3) refocusing the narrative from "unification" to "hierarchical memory." With these changes, it's viable for A* venues.

---

## User

suggest improvements on all of these topics . consider the neurips deadline 06.05.2026 and ARR 25.05.2026. How can we reframe the key contribution / the paper direction to reach the goal in the givet time frame?

---

## Assistant (Plan · qwen_qwen3.5-27b@iq4_xs · 187.7s)

*Thinking:*

The user wants me to suggest improvements and reframe the paper direction given tight deadlines (NeurIPS 06.05.2026, ARR 25.05.2026). I need to analyze what's feasible in ~1.5 months and propose a realistic strategy that leverages existing work while maximizing chances of acceptance.

Let me think about:

1. Current state based on notes (working draft exists, some experiments done)
2. What can realistically be completed by late May 2026
3. How to reframe the contribution for maximum impact with minimum additional work
4. Strategic recommendations for NeurIPS vs ARR submission

I should ask clarifying questions about:

- Current experimental results (what's already working?)
- Available compute resources
- Team capacity
- Whether they prefer NeurIPS main or workshop

Let me provide a comprehensive strategic plan while asking these questions.

# Strategic Plan for RMCA Paper Submission (NeurIPS 2026)

## Timeline Reality Check


| Milestone          | Date       | Days Remaining |
| ------------------ | ---------- | -------------- |
| Today              | 28.03.2026 | -              |
| ARR Deadline       | 25.05.2026 | **58 days**    |
| NeurIPS Submission | 06.05.2026 | **39 days**    |


**Critical Constraint:** You have ~5 weeks for NeurIPS, ~8 weeks for ARR resubmission if needed.

---

## Strategic Options Analysis

### Option A: Full RMCA Paper (High Risk)

- **Scope**: Complete architecture + scaling experiments + theoretical analysis
- **Work Required**: 60-80 days of full-time work
- **Success Probability**: ~30% for NeurIPS, ~50% for ARR cycle
- **Verdict**: Too ambitious for deadline

### Option B: Focused "Training Dynamics" Paper (Medium Risk) ⭐ RECOMMENDED

- **Scope**: Why recurrent models are hard to train + RMCA as solution
- **Work Required**: 30-40 days
- **Success Probability**: ~60% for NeurIPS, ~75% for ARR cycle
- **Verdict**: Realistic and high-impact

### Option C: "Hierarchical Memory" Ablation Study (Low Risk)

- **Scope**: Short-term vs long-term memory comparison on existing models
- **Work Required**: 20-30 days
- **Success Probability**: ~70% for NeurIPS workshop, ~85% for main
- **Verdict**: Safe but less novel

---

## Recommended Strategy: Option B (Training Dynamics Focus)

### Reframed Contribution

**Current Narrative:** "RMCA unifies RMT, ARMT, Mamba" ❌ Too broad, needs more work

**Reframed Narrative:** ⭐

> **"Why Recurrent Models Overfit Faster: A Training Dynamics Perspective"**
>
> We identify that segment-level recurrence suffers from gradient instability and premature convergence. Through systematic analysis across RMT, Mamba, GDN, and our proposed RMCA architecture, we show that (1) memory write operations are the bottleneck, (2) curriculum learning alone is insufficient, and (3) separating short-term from long-term memory updates stabilizes training while improving performance on associative retrieval tasks.

**Why This Works:**

- Leverages existing experiments (RMT, Mamba comparisons already planned)
- Doesn't require full RMCA scaling to 1B+ parameters
- Addresses T1 ("we don't understand how to train recurrent models") from your notes
- Clear mechanistic insight reviewers can evaluate

---

## Revised Paper Structure (4-5 Week Plan)

### Week 1-2: Core Experiments (Priority Order)


| Experiment                              | Purpose                     | Compute Needed | Status        |
| --------------------------------------- | --------------------------- | -------------- | ------------- |
| RMT vs Mamba training curves on AR task | Show overfitting difference | Low            | ✅ Planned     |
| RMCA V0-V4 ablation on same task        | Identify stable variants    | Medium         | ⏳ In progress |
| Gating vs attention for write operation | Test stability hypothesis   | Low            | ❌ Not started |
| Curriculum sensitivity analysis         | When does it help/hurt?     | Low            | ❌ Not started |


**Deliverable by Week 2:** Clear answer to "which RMCA variant trains stably?"

### Week 3: Scaling & Generalization


| Experiment                             | Purpose                        | Compute Needed |
| -------------------------------------- | ------------------------------ | -------------- |
| Memory size scaling (n_mem=8,16,32)    | Capacity vs stability tradeoff | Medium         |
| Context length scaling (4K→32K tokens) | Long-context performance       | High           |
| Downstream transfer (bAbI QA1/QA2)     | Reasoning capability           | Low            |


**Deliverable by Week 3:** Performance benchmarks with error bars

### Week 4: Analysis & Writing

- Gradient norm evolution plots
- Attention visualization (which memory tokens are used?)
- Write paper draft focusing on training dynamics narrative

### Week 5: Polish & Submit

- Reviewer anticipation section (address likely criticisms)
- Related work expansion (TTT, Titans, Atlas comparisons from GradMem notes)
- ARR submission by 25.05

---

## Critical Decisions Needed

### Question 1: What Results Already Exist?

Based on your notes, I see mentions of:

- "RMCA working draft" completed mid-Feb 2026
- Some Mamba/RMT reruns planned for Mar 2026
- Learning rate experiments pending

**I need to know:**

1. Do you have any RMCA training curves already? Which variants work?
2. What's the current performance gap vs Mamba/GDN on AR tasks?
3. Have you observed the "double attention instability" empirically?

### Question 2: Compute Resources Available

Your notes mention:

- GigaLearn access (pending as of Feb)
- Local GPUs (RTX 3090 mentioned for local LLMs)
- Job queue system ("transfer mamba training to jobs")

**I need to know:**

1. How many GPU-hours can you realistically use by May?
2. Can you run 1B+ parameter models, or should we focus on <200M?
3. Is there a student who can help with experiments (SPBSU collaboration)?

### Question 3: NeurIPS Main vs Workshop?


| Venue                      | Acceptance Rate | Effort Required           | Impact          |
| -------------------------- | --------------- | ------------------------- | --------------- |
| NeurIPS Main               | ~25%            | High (must be compelling) | Highest         |
| NeurIPS Track (e.g., COLM) | ~30-40%         | Medium                    | High            |
| Workshop                   | ~50%+           | Low-Medium                | Lower but safer |


**My recommendation:** Target **NeurIPS main via ARR**, with workshop as backup. The training dynamics angle is broad enough for main conference.

---

## Specific Improvements by Category

### 1. IDEA Reframing (Immediate Action)

```
OLD: "RMCA: Unified Recurrent Memory Architecture"
NEW: "Training Dynamics of Segment-Level Recurrence: 
      Why Memory Write Operations Matter"

Key Claims to Prove:
1. Recurrent models overfit X% faster than transformers on same tasks
2. Memory write mechanism (attention vs gating) determines stability
3. Hierarchical memory (short + long term) reduces overfitting by Y%
4. Curriculum helps but doesn't solve the fundamental problem
```

**Why this works:** Each claim can be validated with 1-2 experiments, no scaling required.

### 2. Architecture Simplifications

Given the deadline, **cut these features**:

- ❌ Linear attention variant (too much engineering)
- ❌ Adaptive memory allocation (nice-to-have only)
- ❌ Multi-layer RMCA (start single-layer, add depth if time permits)

**Focus on:**

- ✅ Gating vs attention for write operation (critical insight)
- ✅ Memory size ablation (8, 16, 32 tokens)
- ✅ Single well-tuned variant that works reliably

### 3. Experimental Prioritization

**Must-Have Experiments (Weeks 1-2):**

```
Task: Associative Retrieval (N=50, 100, 200 key-value pairs)
Models: RMT, Mamba, GDN, RMCA-V(best)
Metrics: Exact Match, Training Loss Curves, Gradient Norms

Task: PhoneBook Lookup
Models: Same as above
Metrics: Recall@k across context lengths (1K, 4K, 16K tokens)
```

**Nice-to-Have (Weeks 3-4 if time permits):**

- bAbI QA1/QA2 for reasoning
- Perplexity on WikiText2
- Downstream fine-tuning on translation

### 4. Baseline Strategy

**Minimum Viable Baselines:**


| Model                       | Why Include                           | Effort                          |
| --------------------------- | ------------------------------------- | ------------------------------- |
| Mamba2 (state size matched) | SOTA SSM baseline                     | Medium (tokenizer issues noted) |
| GDN                         | Direct comparison from notes          | Low (code exists)               |
| RMT                         | Your previous work, shows improvement | Low                             |
| Transformer-XL              | Recurrent attention baseline          | Low                             |


**Cut These:** RWKV (tokenizer problems), Longformer (different paradigm), Linear Transformers (not direct competitors)

### 5. Narrative Angles for NeurIPS Reviewers

**Angle 1: Training Recipe Contribution**

> "We provide the first systematic analysis of why recurrent models fail to train, with actionable recommendations (gating > attention for writes, hierarchical memory separation)."

**Angle 2: Mechanistic Insight**

> "Through gradient flow analysis and attention visualization, we identify that unstable write operations cause premature convergence—a problem solved by RMCA's separated memory streams."

**Angle 3: Practical Impact**

> "Our findings enable training of recurrent models without extensive curriculum tuning, making them viable for long-context applications."

---

## Risk Mitigation Plan


| Risk                                     | Probability | Mitigation                                                           |
| ---------------------------------------- | ----------- | -------------------------------------------------------------------- |
| RMCA doesn't train stably                | Medium      | Fall back to "analysis paper" showing why it fails + recommendations |
| Mamba tokenizer issues block experiments | High        | Use GDN + RMT as primary baselines; add Mamba if fixed               |
| Results don't show clear improvement     | Low-Medium  | Focus on training dynamics insights rather than SOTA claims          |
| Compute runs out                         | Medium      | Scale down to 50M models, emphasize qualitative findings             |


**Backup Plan:** If RMCA doesn't work by Week 3, pivot to:

> "A Diagnostic Study of Recurrent Model Training Failures" — still publishable as analysis paper.

---

## Clarifying Questions for You

Before finalizing the plan, I need your input on:

1. **Current experimental status:** What RMCA variants have you actually trained? Do any work reliably yet?
2. **Compute availability:** Can you run ~10-20 training experiments of 50-200M models over the next 4 weeks? Or should we plan for smaller scale?
3. **Team capacity:** Will SPBSU students help with experiments (you mentioned 2-3 students)? This could double throughput.
4. **Risk tolerance:** Do you prefer:
  - Aggressive: Full RMCA paper, risk rejection, aim for NeurIPS main
  - Conservative: Training dynamics analysis, safer acceptance, workshop or track
5. **Mamba status:** Your notes mention tokenizer issues with RWKV/Mamba. Is this resolved? If not, should we drop these baselines entirely?

---

## Next Steps (Once You Answer)

1. Finalize paper scope and narrative
2. Create detailed experiment checklist with priority ordering
3. Set up shared tracking sheet for results
4. Draft introduction + method sections while experiments run
5. Weekly checkpoints to assess progress vs timeline

**My recommendation:** Go with Option B (Training Dynamics focus), target NeurIPS main via ARR, use 4 weeks for core experiments + 1 week for writing. This balances ambition with realism given the deadline.

---

