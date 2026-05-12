# RMCA-GDN Paper: Narrative Analysis & Improved Structure

**Context:** Component surgery paper on recurrent sequence models. Targeting ARR May 25, 2026. Core architecture: RMCA-GDN (segment-level Memory Transformer with GDN as long-term memory).

**Purpose of this document:** Diagnose problems with current narrative, propose restructured version, prioritize remaining experiments.

---

## 1. Assessment of Current Narrative

### What Works

- **Motivation is honest and well-grounded.** "At some point you have to stop storing all tokens" is inarguable. Framing compression as both computational and statistical gives two independent reasons.
- **Logical chain is clean:** compression necessary → recurrence necessary → current recurrent models have a bottleneck.
- **GDN as diagnostic tool is well-motivated.** Not just proposing a new architecture, but explaining *why* segment-level models fail by comparing against token-level models that succeed.

### Problems

#### Problem 1: Narrative promises a result we don't have

The story builds toward "segment-level model based on GDN that outperforms token-level GDN" — but this result doesn't exist yet. The paper's actual strength is the **diagnostic analysis** (capacity bottleneck + write mechanism explain the gap), not RMCA-GDN as an artifact.

**Fix:** Restructure so diagnosis is the main claim, RMCA-GDN is validation.

#### Problem 2: "Softmax noise from the long tail" is weak

Reviewers will push back — FlashAttention etc. handle long sequences without softmax noise being the practical bottleneck. The computational argument suffices.

**Fix:** Replace second motivation leg with **memory cost**: "Storing all KV pairs scales linearly in memory, making deployment on fixed-memory devices impossible regardless of computational tricks."

#### Problem 3: Jump from "RMT/ARMT fail" to "look at SSMs" is unmotivated

Implicit claim: "let's look at a completely different architecture family to understand why ours fails." Missing step: **what do SSMs and segment-level models have in common?**

**Fix:** Make explicit that both maintain a fixed-size state compressing a growing sequence. They're solving the same compression problem at different granularities. Comparison becomes natural.

#### Problem 4: "Segment size = 1 → GDN/Transformer hybrid" is buried

This is the **key theoretical insight** of the framework. RMCA-GDN parameterized by segment size S gives a continuum: S=1 is token-level GDN, S=N is segment-level recurrence. Real contribution = **a lens unifying token-level and segment-level recurrence as endpoints of a single axis**, not "a new model."

**Fix:** Lead with the unification framing.

---

## 2. Improved Narrative Structure

### §1. Fixed-state recurrence is inevitable (motivation, ~1 paragraph)

Quadratic attention cost and linear KV-cache growth make full-context transformers impractical at scale. Any deployable long-context model must compress history into a fixed-size state. Recurrence — explicit or implicit — is unavoidable.

### §2. Two families of fixed-state recurrence (framing — new and important)

| Family | Examples | State capacity | Write mechanism |
|--------|----------|----------------|-----------------|
| Token-level | GDN, DeltaNet, Mamba | d × d_state matrix | Rank-1 update per token |
| Segment-level | RMT, ARMT | n_mem × d | Cross-attention over full segment |

Both solve the same problem — compress growing sequence into fixed state — but differ in **granularity** and **information available at write time**.

### §3. Segment-level models currently fail where token-level succeeds (empirical)

Present AR results:

| Model | Config | Exact Match (N=8 K2V2) |
|-------|--------|------------------------|
| Mamba | ss16 ck4 | ~99.6% |
| RMT | mem=1 | ~2.7% |
| ARMT | mem=1 | ~2.9% |

Striking gap.

### §4. Diagnosis: capacity bottleneck, not architectural family (core contribution)

- SSM ablation shows state size dominates AR performance.
- ARMT with mem=1 → effective capacity 1×d.
- GDN with state_size=16 → d×16.
- At matched parameters, capacity difference explains most of the gap.
- **Supporting evidence:** increasing n_mem_tokens in RMCA recovers performance (0.074→0.463 at N=8).

### §5. RMCA-GDN: unifying the two families (validation, not headline)

Plug GDN as inter-segment recurrence in a segment-level architecture. Result: a model parameterized by segment size S.

- S=1 → token-level GDN
- S=N → segment-level with full intra-segment attention

**Not a new architecture** — a controlled experimental framework for asking: *does intra-segment deliberation before writing improve state utilization?*

### §6. When does segment-level deliberation help? (experiments)

Tasks designed to require multi-token information for write decisions:

- **Task A (priority): Noisy AR** — distractor tokens between KV pairs
- **Task B: Multi-token AR** — composite keys/values requiring binding

**Prediction:** when deciding *what to write* requires simultaneous access to multiple tokens, segment-level write outperforms sequential rank-1 updates.

---

## 3. Critical TBD Experiments

### 3.1 Capacity-matched comparison [ESSENTIAL]

**Goal:** Quantitative backbone of the capacity bottleneck argument.

**Procedure:**
- Compute effective state capacity:
  - ARMT: `n_mem × d_model`
  - GDN: `d_model × d_state`
- Match them (e.g., ARMT n_mem=16, d=128 ↔ GDN d=128, d_state=16)
- Compare on AR benchmark

**Outcomes:**
- If gap closes substantially → strongest result of the paper
- If gap remains → write mechanism matters independently of capacity (also publishable)

### 3.2 Task A: Noisy AR [HIGH PRIORITY]

Insert D distractor tokens between KV pairs:
```
k1 v1 [D noise tokens] k2 v2 [D noise tokens] ... query
```

**Why RMCA wins (theoretically):** Self-attention identifies signal vs noise within segment before writing. GDN must process each noise token through state update, accumulating rank-1 perturbations.

**Vary:** D ∈ {0, 4, 8, 16}. Expect gap to widen with D.

**Control:** segment size aligned/misaligned with KV pair boundaries.

### 3.3 Task B: Multi-token AR [SECONDARY]

Multi-token keys/values:
```
[k1a k1b] [v1a v1b] [k2a k2b] [v2a v2b] ... [query_a query_b]
```

**Variant:** key-value association depends on combination, not either alone (k=[3,7]→v=[2,5], k=[3,9]→v=[8,1]).

**Why RMCA wins:** Self-attention binds k1a+k1b into composite key before writing. GDN must form composite incrementally.

### 3.4 PARK: State-only training experiment

Originally proposed: train only recurrent state, measure PPL on 2nd segment (prompt-tuning analogy).

**Defer.** Risk: requires LM setup, hard to interpret cleanly (backbone quality vs state quality confound). Pursue only if core experiments finish early.

---

## 4. Drop From Scope (Insufficient Time)

- MqAR (Zoology)
- S-NIAH-2/3 (real essays)
- Selective Copying
- ATR (Arora 2025)
- Formal languages / Dyck-k
- State tracking S3/S5

Use existing AR task + Task A (Noisy AR) as the two evaluation tasks. Task B if time allows.

---

## 5. Timeline (2-3 weeks to ARR May 25)

### Week 1 (now)
- **Day 1-2:** Capacity-matched ARMT vs GDN comparison (§3.1)
- **Day 3-5:** Implement Noisy AR task, run RMCA-GDN vs baselines (§3.2)
- **Day 6-7:** Analyze results, decide if Task B is worth pursuing

### Week 2
- Compile SSM ablation figures (existing data)
- Run capacity-matched experiments at scale
- Begin paper draft with new narrative structure

### Week 3
- Buffer + writing
- ARR submission

---

## 6. Key Framing Shift (Critical for Agent)

**OLD framing:** "We propose RMCA-GDN, a new architecture that combines segment-level memory with GDN-style state updates."

**NEW framing:** "We diagnose why segment-level recurrence underperforms token-level recurrence on associative recall, identify capacity bottleneck as the dominant factor, and introduce a unified framework parameterized by segment size that connects the two families."

**Why this matters:** Robust to negative results. Even if RMCA-GDN doesn't cleanly beat GDN, the diagnostic finding ("segment-level deliberation doesn't help beyond capacity matching") is publishable. Sells the lens, not the artifact.

---

## 7. Anchor Results (Already in Hand)

- SSM component ablation (d/ss/ck/n_layer) on N8/N16 K2V2
- ARMT N=8 best EM=0.5052 with LayerNorm + n_mem scaling
- N=16 collapse (negative result — frame as motivation for capacity argument)
- Weight decay=0.01 critical for autoresearch convergence at N=4
- RMCA requires skip connection + LayerNorm to learn at all

---

## 8. Open Questions for Agent to Resolve

1. What is the precise effective state capacity formula for ARMT vs GDN at matched parameters? (Need exact formulas with all constants)
2. Does the N=16 collapse persist when ARMT mem is scaled to match GDN d_state capacity?
3. At segment size S=1, does RMCA-GDN exactly reduce to GDN, or is there residual structure (intra-segment self-attention over 1 token = identity)? Verify mathematically and empirically.
4. For Noisy AR: optimal segment size relative to noise density D?
