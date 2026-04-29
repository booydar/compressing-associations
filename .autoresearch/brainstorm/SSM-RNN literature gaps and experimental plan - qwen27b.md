# SSM/RNN literature gaps and experimental plan

**Session ID:** ses_2985cc2c1ffe35501fgP21WImH
**Created:** 4/7/2026, 2:10:44 PM
**Updated:** 4/7/2026, 2:26:33 PM

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

1. Tasks That Successfully Distinguish Models Most Discriminative Tasks:  
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

---

## ...

## Summary of Current State

**Completed:**

- RMCA working draft with V1-V3 variants
- 130+ RMT experiment runs on KV retrieval
- Baselines: GDN, LSTM, Mamba, RWKV, Linear Attention
- Infrastructure: KV retrieval dataset, training scripts, HuggingFace integrations

**Active:**

- NeurIPS 2026 deadline (May 15)
- RMCA as primary focus through W19

**Key Open Questions:**

1. What component drives GDN's success on AR?
2. Why is double attention hard to train with recurrence?
3. How to write useful information to memory?

---

## Proposed Experimental Plan

Based on the literature gaps and current state, here's a **publishable experiment set** targeting **ARR/NeurIPS 2026**:

### **Paper Title (Working):** "Component Surgery for Recurrent Memory Models: What Makes SSMs Work?"

### **Core Narrative:**

Instead of asking "which architecture is better," systematically transplant components (state size, write mechanism, gating) across architectures to identify what actually matters for long-context tasks.

---

### **Phase 1: State Capacity at Matched Parameters (4 weeks)**

**Literature Gap:** M2RNN shows state size matters, but no cross-architecture comparison

**Experiments:**

1. **Matched-parameter comparison** on MqAR + S-NIAH-2:
  - RNN/GRU (vector state d=128) vs Mamba2/GDN (matrix state √d×√d) vs RMCA (mem_tokens×d)
  - Keep total parameters constant, vary state geometry
2. **Effective capacity measurement:**
  - Train each at matched params (5M, 10M, 20M)
  - Measure: tokens compressible per state dimension before EM drops below 90%

**Expected outcome:** Quantify "state efficiency" across representations

---

### **Phase 2: Write Mechanism Transplants (6 weeks)**

**Literature Gap:** No paper systematically adds delta rule to RMT, or gating to other architectures

**Experiments:**

1. **Delta rule into RMCA:**
  - Replace cross-attention write with: `Mem ← Mem + Δ ⊙ (h - Mem)`
  - Compare to GDN baseline
2. **Gating into Linear Attention:**
  - Add input-dependent gates to FLA: `g_t = σ(Wx_t) ⊙ s_t`
  - Test on Selective Copying task
3. **Hybrid RMCA-GDN:**
  - RMCA read (cross-attention) + GDN write (delta rule)
  - Does this fix RMCA's training instability?

**Expected outcome:** Show that write mechanism can be transplanted and improves weaker architectures

---

### **Phase 3: Input-Dependence Ablation (3 weeks)**

**Literature Gap:** Papers show input-dependence helps, but don't explain induction vs direct retrieval

**Experiments:**

1. **RMCA variants on ATR task** (Arora 2025):
  - Static filters (LTI-style) vs input-dependent gates
  - Use mechanistic probes to identify which layers learn induction vs retrieval
2. **Comparison to Mamba's selective mechanism:**
  - Is RMCA's cross-attention Q from H_t enough input-dependence?

**Expected outcome:** Link architectural choice to learned mechanism (induction vs retrieval)

---

### **Phase 4: Depth Interactions (2 weeks)**

**Literature Gap:** How depth interacts with state capacity and write mechanism

**Experiments:**

1. **Depth sweep at fixed params:**
  - L=2,4,8,12 layers with correspondingly smaller/d states
  - Track: when does "skip connection click" (from your notes)?
2. **Curriculum necessity by depth:**
  - At what depth does curriculum become essential?

**Expected outcome:** Training recipe for deep recurrent models

---

### **Discriminative Task Suite**

Based on literature review, use:

1. **MqAR** (Zoology) - distinguishes attention vs gated convs
2. **S-NIAH-2/3** (GDN) - real-world essays, distinguishes memory management
3. **Selective Copying** (Mamba) - distinguishes LTI vs selective SSMs
4. **ATR** (Arora 2025) - for mechanistic analysis

---

### **Timeline to NeurIPS (May 15)**


| Phase                | Weeks                  | Deliverable                      |
| -------------------- | ---------------------- | -------------------------------- |
| 1: State capacity    | W14-W17 (Apr 13-26)    | Fig 1: state efficiency curve    |
| 2: Write transplants | W15-W20 (Apr 20-Jun 7) | Fig 2: component surgery results |
| 3: Input-dependence  | W18-W20 (May 4-15)     | Fig 3: mechanistic probes        |
| 4: Depth + writeup   | W19-W21 (May 11-25)    | Paper draft                      |


**Buffer:** 2 weeks before ARR deadline (May 25)

---

### **Clarifying Questions:**

1. **Compute availability:** Do you have access to run 50-100 experiment runs (4-6 GPUs for 4-6 weeks)? The transplant experiments require training ~20 model variants.
2. **Codebase priority:** Should I focus the plan on:
  - Option A: RMCA-centric (transplant components INTO RMCA)
  - Option B: Architecture-agnostic (compare all architectures equally)
3. **Target venue:** ARR→NeurIPS (broader ML audience) or ARR→ICLR (more receptive to architecture papers)?
4. **Student involvement:** Are SPBSU students available to own specific experiment tracks (e.g., one student on Phase 1, another on Phase 2)?

Let me know your preferences and I'll refine the plan with specific experiment configs and code modifications needed.

---

