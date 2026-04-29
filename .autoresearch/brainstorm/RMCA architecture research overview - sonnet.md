# RMCA architecture research overview

**Session ID:** ses_2cbdb9826ffeq76uV181IIET0B
**Created:** 3/28/2026, 2:11:34 PM
**Updated:** 3/28/2026, 2:46:47 PM

---

## User

RN i'm working on this RMCA architecture. The notes on research, todo etc are stored in the ./obsidian-db folder in this directory. Find all the relevant info in my notes that u can find, the idea of the method, the objectives and the current state -- how its performing, whats on the agenda and current limitations/directions for the future.

---

## Assistant (Plan · claude-4.6-sonnet-medium-thinking · 91.4s)

Here's the full picture from your notes:

---

## RMCA — Recurrent Memory Cross-Attention

### The Idea

**Goal:** make training for recurrent models easier and better by separating memory parameters and making them act per-token with dedicated read/write operations.

**Core mechanism:** Memory is a matrix `n_mem × hidden_dim` per layer, stored horizontally in a residual stream (stays in its layer). Read and Write use T5-style cross-attention:

```
H_L-tmp ← H_L-1 + CrossAttention( LN(H_L-1), LN(Mem_L) )   # Read
H_L     ← H_L-tmp + TransformerBlock( LN(H_L-tmp) )
Mem_L-next ← Mem_L + CrossAttention( LN(Mem_L), LN(H_L) )   # Write
```

**Unifying claim:** RMCA generalizes RMT, ARMT, and Mamba/GDN under one framework. By varying how many tokens participate in cross-attention (per-token → full segment), you interpolate between Mamba-like and ARMT-like behavior. Linearizing cross-attention gives ARMT; it can also recover Mamba/RWKV.

**Memory type taxonomy (from 2026-03-16 notes):**

| model  | short R | short W | long R | long W |
|--------|---------|---------|--------|--------|
| RMCA   | S-Attn  | S-Attn  | C-Attn | C-Attn |
| RMT    | S-Attn  | S-Attn  | S-Attn | S-Attn |
| Mamba  |         |         | gate   | gate   |
| GDN    |         |         | gate   | gate   |

**Write variants being ablated:**

- **V1:** `Mem_L-next ← Mem_L + CrossAttention( LN(Mem_L), LN(H_L-1) )`
- **V2:** `Mem_L-next ← Mem_L + CrossAttention( LN(H_L), LN(H_L-1) )`
- **V3:** uses separate filtered read + write (trainable) tokens; write goes `CrossAttention( LN(write), LN(H_L-1) )`
- **V4:** TBD

---

### Current State

**Working draft exists** (from ~Feb 2026). Active experiments on the associative retrieval / compression-association benchmark comparing:

- **Memory sizes:** mem1, 2, 4, 8, 16, 32, 64
- **Token selection N:** N2, N4, N8, N32
- **Baselines:** GDN (Gated DeltaNet, at dim 128→4), LSTM, sLSTM, GRU, Elman RNN, Delta Net, RWKV, Mamba, Linear Attention (2020)
- **RMCA-2.0** variant exists in the results
- LR schedules being tested: `3e-04 → 1e-03`

**Key findings so far:**
- GDN's update rule appears to be the key driver for good associative retrieval (per ICML review feedback)
- The hypothesis: double attention (short-term S-A + long-term C-A simultaneously) is hard to train with recurrence
- Writing to memory via cross-attention has a known issue: queries should come from H_L (what you're thinking about), not from memory. In V2, memory hasn't seen the input yet before the write.

**Core open question (as of Mar 2026):** "What is the core problem of RMCA / segment-level recurrence? How to simplify the aggregating function?"

---

### Active Agenda

**Timeline:** RMCA is the primary research focus from W12 through W19 (now through mid-May 2026), targeting the **NeurIPS 2026 deadline (May 15)**.

Immediate experiment todos:
- Multi-layer MCA write
- Add FF layers to memory
- Gating: turn off cross-attention → learnable gate `a`, where `h ← a*h + (1-a)*mem`
- Reduce number of heads → 1
- Memory shift to input of *next* layer (instead of same)
- Match RMCA to Gated DeltaNet token-by-token (equivalence proof by construction)
- Fix RWKV tokenizer (outputs gibberish with FLA 1B) and run training
- Find what tasks segment-level models should be *better* on: dense local info, limited global transfer

---

### Key Limitations / Open Problems

1. **Hard to train with recurrence** — double attention is unstable; unclear which component matters for associative retrieval
2. **Write objective is unclear** — cross-attention write lacks direct feedback from prediction; "we don't know how to write useful information into memory" (T1.1 in your research problem taxonomy)
3. **Limited memory capacity** — inherits RNN-style fixed-size state constraint
4. **Architecture comparison unclear** — need to understand why GDN beats RMCA on AR and what specific component drives it

### Future Directions Under Consideration

- **Sigmoid instead of softmax** in memory cross-attention → dense writes (more tokens per memory vector)
- **Context dropout** — randomly hide segments to force memory reliance
- **Deep supervision** — auxiliary losses at segment boundaries
- **Multi-token prediction for planning** — predict next memory token as implicit lookahead
- **Linearization** — distill from a pretrained Transformer to bypass hard recurrent training
- **Expressivity analysis** — formal comparison RMT vs looped Transformer vs SSM

---

The project is at the "working draft + ablation" stage, with the core architectural question still open (what simplification of the write/aggregate function makes RMCA trainable and competitive with GDN). The NeurIPS deadline is the forcing function.

---

## User

provide a comprehensive analysis: idea (novelty, impact, formalization), architecture (adequacy, component efficiency), experimental approach (adequacy, datasets, baselines) and overall high-level comments. Then suggest improvements on all of these topics . consider the neurips deadline 06.06.2026 and ARR 25.06.2026

---

## Assistant (Plan · claude-4.6-sonnet-medium-thinking · 128.5s)

Here is a comprehensive analysis, based on everything in your notes.

---

## 1. Idea: Novelty, Impact, Formalization

### Novelty

**Genuine.** The per-layer horizontal memory residual stream with dedicated T5-style cross-attention read/write is a concrete design choice that hasn't been explored in this exact form. The unifying claim — that RMCA interpolates between RMT/ARMT and Mamba/GDN by varying how many tokens participate in cross-attention — is a strong theoretical contribution if formalized properly.

**Risk of overclaiming.** "Generalizes RMT, ARMT, Mamba, GDN" is a bold claim that will attract immediate scrutiny. Mamba uses a structured SSM recurrence with HiPPO init, not cross-attention. The interpolation/linearization argument needs a formal equivalence proof, not just an intuition. As of now, your notes flag this as TBD. Without a precise theorem (or at least a construction), reviewers will push back hard — as the ICML GradMem review already shows.

**Differentiation from Titans/ATLAS.** The TTT/Titans space is now crowded. RMCA is structurally different (segment-level, layer-local memory, no meta-gradient write), but the narrative must be watertight. Your GradMem review experience (R3W1 on originality) is a preview of what RMCA will face.

### Impact

If the architecture actually trains stably and beats GDN on associative retrieval — currently the open question — the impact is meaningful: a trainable segment-level model with a principled read/write decomposition. If it doesn't beat GDN, the paper degrades to an ablation study of a framework, which is publishable but not a strong NeurIPS contribution. The impact hinges entirely on resolving whether RMCA can match GDN.

### Formalization

**Currently weak.** The formalization is at the "recipe" level — four write variants (V0–V3), an intuitive table (short R/W × long R/W), a generalization claim. What's missing:

- A formal definition of when RMCA reduces to ARMT (linearization conditions)
- A formal definition of when it reduces to Mamba/GDN (equivalence by construction — your notes flag this as a TODO: "match RMCA to GDN token-by-token")
- A precise capacity analysis (how many key-value pairs can RMCA store with `n_mem` tokens at dimension `d`?)
- No complexity analysis of the recurrence in segment-level vs. token-level settings

The memory taxonomy table is the right starting point but is too informal for a theory paper and too sparse for an empirical paper. It needs to either become a formal theorem or be replaced by empirical ablations that operationalize each cell.

---

## 2. Architecture: Adequacy and Component Efficiency

### Read Operation

```
H_L-tmp ← H_L-1 + CrossAttention( LN(H_L-1), LN(Mem_L) )
```

**Adequate.** T5-style cross-attention for reading is principled — queries come from the hidden stream, keys/values from memory. This is correct directionally: "we want to read what we're thinking about." The pre-norm structure (LN before both) is sound. The main concern is cost: full cross-attention over `n_mem` memory vectors per layer adds `O(T · n_mem · d)` per layer, which is non-negligible if `n_mem` grows.

### Write Operation

This is the core weakness, and your notes acknowledge it:

- **V0/V1:** Query comes from memory itself (`LN(Mem_L)`). Memory queries itself against hidden states. This is "what does memory want to know" — not "what does the model want to remember." Mechanistically wrong as a primary write.
- **V2:** `CrossAttention(LN(H_L), LN(H_L-1))` — queries from the updated hidden state, keys/values from pre-update. The note correctly flags: "memory hasn't seen the input yet" before the write in V2. This creates an information ordering problem.
- **V3:** Separate trainable write tokens, which is a cleaner design, but adds parameters and complexity.

**The fundamental problem:** All write variants share the same issue — there is no direct feedback path from the prediction loss to the write operation. Cross-attention writes are optimized through gradients flowing back through the full segment, making the write objective implicit and difficult to train. This is your T1.1 problem ("we don't know how to write useful information into memory").

### Memory Storage

The `n_mem × d` matrix per layer is a reasonable design. However:
- Memory lives in its layer ("horizontal residual stream") — this prevents cross-layer memory composition, which may limit expressivity
- The fixed size inherits all RNN capacity limitations
- No mechanism to forget or overwrite selectively (unlike GDN's gated update)

### Double Attention Problem

Your notes identify this correctly: "double attention (short-term S-A + long-term C-A simultaneously) is hard to train with recurrence." This is the crux. The model must simultaneously learn:
1. Self-attention within the segment (short-term)
2. Cross-attention to/from memory (long-term)
3. The recurrent update rule across segments

Three interacting optimization targets with only one loss signal. GDN avoids this by using a single gated recurrence — structurally simpler and empirically better on AR.

---

## 3. Experimental Approach: Adequacy, Datasets, Baselines

### Datasets

**Associative retrieval (compression-association benchmark)** is a good diagnostic — it directly tests key-value memory capacity. Your results showing GDN dominance here are informative. However:

- **Single-task focus is a risk.** For NeurIPS, a single synthetic benchmark won't be sufficient. You need at least 2–3 task families: AR + something testing sequential/temporal dependencies (where segment models should win) + a real-language task.
- **"Where do segment models win?"** is still an open question in your notes (W12 agenda). This is not just a nice-to-have — it's the *narrative core*. Without a task family where RMCA > GDN, the paper has no positive result to anchor around.
- **Missing:** BABILong, phonebook lookup, or real-NLP tasks (at least perplexity on a language modeling benchmark). These are listed in your codebase but not in the current results.

### Baselines

Good coverage of the RNN/SSM family: Elman, LSTM, sLSTM, GRU, Linear Attention (2020), DeltaNet, GDN, RWKV, Mamba. This is the right set. Problems:

- **RWKV is broken** (tokenizer outputs gibberish with FLA 1B, training crashes with architectural errors). This is a known blocker and it's still open.
- **No Transformer baseline.** For a memory paper, showing the gap between a full-attention Transformer and RMCA on the same tasks is essential — both to show why recurrent memory is needed, and to show what RMCA recovers.
- **No ARMT baseline.** Since RMCA claims to generalize ARMT, the comparison is logically required.
- **GDN dim 128→4** is a specific configuration. Is this the fairest comparison? Match by parameter count or by state size — not an arbitrary dimension ratio.

### Hyperparameter Sweep

LR sweep `3e-04 → 1e-03`, memory sizes `mem1` through `mem64`, N2/N4/N8/N32 — good range, but:
- It's unclear whether the N parameter (tokens participating in cross-attention) is being swept at the same memory size, or whether results are confounded
- RMCA-2.0 variant appears in the results but isn't defined in the notes — what changed?

### Evaluation

**Exact match on AR** is appropriate. But:
- No sample efficiency curves (does RMCA train faster with less data?)
- No out-of-distribution length generalization (test on sequences longer than training)
- No wall-clock comparison (cross-attention read/write adds real cost — is RMCA slower than GDN per step?)

---

## 4. Overall High-Level Comments

**Where you are:** A working architecture with an interesting unifying story, active ablations, and a clear empirical gap (GDN wins on AR). The paper is not yet a paper — it's a set of experiments that could become one.

**The central deficit:** You don't yet have a positive result. Every finding so far is "RMCA doesn't beat GDN" or "this write variant has this problem." A NeurIPS paper needs at least one strong positive result. The story "we unified four architectures but haven't beaten any of them yet" will get rejected.

**The theoretical claim is the strongest asset**, but it's currently the least developed piece. If you can prove: (a) RMCA with linear CA = ARMT, (b) RMCA with 1-token CA = Mamba/GDN by construction, and (c) show empirically that interpolating between these recovers different performance profiles — *that* is a NeurIPS paper even without beating GDN.

**The write problem is the load-bearing unsolved issue.** Until you have a principled write mechanism with feedback, every variant (V0–V3) is a heuristic. The GDN's gated update (`Δ`-rule) works precisely because it has a structural inductive bias toward associative recall. RMCA needs an equivalent.

---

## 5. Improvements

### On the Idea / Formalization

1. **Prove the equivalences.** Make the "RMCA generalizes..." claim a formal theorem. The construction "RMCA with 1 token and linear CA = GDN" is in your notes as a TODO — this is the single most important theoretical piece. Do this first.
2. **Reframe the contribution.** If RMCA doesn't beat GDN yet, reframe: "We introduce a parameterized family of recurrent architectures that subsumes SSMs and RMT, and identify which axis of variation drives associative retrieval performance." This is honest and still publishable.
3. **Make the capacity claim precise.** With `n_mem` vectors of dimension `d`, what is the maximum number of key-value pairs that can be stored and retrieved at error rate ε? This is answerable analytically (Hopfield-style counting argument) and empirically (your AR sweep).

### On the Architecture

4. **Fix the write direction.** V3 (trainable write tokens) is the most principled current option, but the queries should come from the updated hidden state `H_L`, not from a fixed learnable token. Try: `Mem_L-next ← Mem_L + CrossAttention(LN(H_L), LN(H_L-1))` but with `H_L` attending to *all* prior hidden states, not just one layer back.
5. **Add a forget gate.** All V0–V3 are purely additive (`Mem + Δ`). A multiplicative gate `Mem_L-next ← g ⊙ Mem_L + (1-g) ⊙ CrossAttention(...)` gives the model the ability to overwrite stale memories — this is the key mechanism in GDN that RMCA currently lacks.
6. **Try sigmoid instead of softmax in cross-attention.** Already on your list. This is a cheap experiment with potentially large impact: dense writes allow memory to accumulate information from multiple tokens per step rather than winner-take-all.
7. **Reduce heads to 1 for the memory cross-attention.** Also on your list. Simpler optimization landscape, and for a `n_mem × d` memory, multi-head is likely redundant.
8. **Consider GDN-style initialization for memory.** Your notes note that HiPPO/S4/exponential matrix initialization is key for Mamba/GDN but not yet tried for RMCA memory. This is a low-cost high-signal experiment.

### On the Experimental Approach

9. **Find the task where RMCA wins.** This is the critical open question (your W12 agenda item). Hypothesis: segment-level models should win on tasks with **dense local structure + limited global information transfer** (e.g., summarization, multi-hop reasoning within segments, or tasks requiring sequential composition over windows). Design a synthetic task that operationalizes this and run it immediately.
10. **Add Transformer and ARMT baselines.** Both are logically required and embarrassingly absent from current results.
11. **Fix RWKV.** This is a known blocker for 2+ weeks. Either downgrade to a working FLA version or replace with a different RWKV variant. Don't go to NeurIPS without this.
12. **Add length generalization evaluation.** Train on length L, test on 2L and 4L. This is the defining test of recurrent memory and is missing.
13. **Controlled parameter-matched comparison.** All comparisons should be matched on total parameter count and on effective state size. GDN dim 128→4 is a specific choice — report it and justify it.
14. **Add context dropout.** Already on your list as a training regularizer. This is cheap (2 lines of code) and may materially help the write operation by forcing the model to rely on memory.

### On the Timeline (NeurIPS June 6 / ARR June 25)

Given today is March 28:

| Milestone | Target |
|---|---|
| Equivalence proof (RMCA → GDN token-by-token) | April 7 |
| Fix RWKV + add Transformer/ARMT baselines | April 14 |
| Forget gate + sigmoid CA experiments | April 21 |
| Find the "RMCA wins" task family | April 28 |
| Full benchmark results (AR + 2 new tasks + LM) | May 12 |
| Paper draft v1 | May 19 |
| NeurIPS submission | June 6 |

**Honest assessment:** NeurIPS June 6 is reachable only if the equivalence proof and a positive result (either on a new task or via the gated/sigmoid fix) land in the next 3 weeks. If you're still in "RMCA doesn't beat GDN" territory by late April, ARR June 25 is the realistic target — it gives you 6 more weeks and the ability to revise in response to reviews for ACL/EMNLP 2027.

The architecture itself is worth building and publishing. The current bottleneck is not the idea — it's the absent positive result and the unproven theoretical claims.

---

## User

i misspelled, both neurips and arr are in may, not june.. So i don't think we'll make it with RMCA - too much yet to improve and the path is not clear. But maybe we should rewire the flow to distinguishing differences between sequence processing models? we have simple nonlinear elman rnn < lstm < slstm < rmt ~= armt < rmca ~= rwkv < mamba < delta net < gated delta net. Take for example a couple new tasks (copying, formal languages mb? suggest) and find the model separation more clearly (if not done in fla papers already). then based on the findings maybe change 1-2 gates/components and prove that they are the key factor. What do u think on that? what else can we do in the given time period? answer all provided questions 

---

## Assistant (Plan · claude-4.6-sonnet-medium-thinking · 79.2s)

Good pivot instinct. Let me think through this carefully.

---

## On the Pivot Strategy

**The reframe is sound.** Shifting from "we built a better model" to "we explain what separates models" is achievable in 4–5 weeks where the RMCA story is not. You already have most baselines running. The story becomes: *capability separation as a function of architectural components*, with 1–2 ablations proving causality. This is publishable at NeurIPS/ARR as an analysis/position paper if executed cleanly.

**The risk:** this space is partially occupied. Zoology (Arora et al. 2023) uses MQAR to show linear attention vs. softmax separation. Based/Hedgehog extend it. Mamba includes selective copying. FLA papers benchmark against each other. **Your gap must be:** a principled task suite spanning the *full hierarchy* you described (Elman → GDN) that identifies *which specific component* at each tier is load-bearing — not just which model wins.

---

## On Task Selection

### What's Already Done (avoid redundancy)
- **Copying / selective copying** — Mamba paper, S4, nearly everything. Overdone.
- **Associative recall (single-query AR)** — Zoology, Based, your current benchmark. You have results, but no separation story yet.
- **LRA (Long Range Arena)** — standard, but doesn't cleanly separate the hierarchy you described.

### Good Options for Separation

**1. Formal languages (Chomsky hierarchy) — strongest pick**
Maps directly to a theoretical hierarchy and gives you formal grounding:

| Language class | Minimal model needed | Example task |
|---|---|---|
| Regular | Elman RNN | `a*b*` membership, parity |
| Deterministic CFL | LSTM | balanced brackets `(){}[]` |
| Non-deterministic CFL | unclear — interesting! | Dyck-2 with ambiguity |
| Counting / CSL | SSMs? RMCA? | `aⁿbⁿcⁿ` counting |

The Bhattamishra et al. (2020) and Merrill et al. work establishes some of this theoretically for Transformers. There's much less done for the SSM/gated-RNN tier. **This is the clearest gap.**

**2. Multi-query associative recall (MQAR)** — already in Zoology, but you can extend it: vary the number of concurrent keys (K=1 vs K=8 vs K=32) and show where each model tier fails. You have the AR infrastructure, so this is cheap.

**3. State tracking** — model must track M simultaneous boolean variables updated by a sequence of operations (e.g., Hahn 2020 "Theoretical Limitations of Self-Attention"). Tests orthogonal dimensions from AR. Maps cleanly to the gate/forget axis.

**4. Hierarchical composition** — nested bracket matching with depth D. Tests whether models can compose local memories into hierarchical structure. Elman fails at D>1, LSTM handles D~5, unclear where SSMs land.

**Best combination for the paper:** MQAR (you already have it) + Formal languages (Dyck-k and/or aⁿbⁿcⁿ counting) + State tracking. Three task families, clean theoretical grounding, no direct overlap with existing FLA benchmarks.

---

## On the "1–2 Components" Ablation

This is the strongest part of the proposal. The hypothesis structure would be:

- **Forget gate** (Elman → LSTM): enables bounded-depth recursion, solves Dyck-1 but not counting
- **Delta/associative update** (LSTM → DeltaNet): enables fast key-value overwrite, solves MQAR
- **Gated delta** (DeltaNet → GDN): stabilizes the associative update under distribution shift, solves MQAR at scale
- **Segment memory** (GRU/LSTM → RMT): extends context window, doesn't help AR within-segment

If you can run ablations that turn each component on/off within a controlled base model and show monotone capability changes — that's the paper. It doesn't require RMCA to be better than anything; it requires RMCA (or a stripped-down version) to be a *controllable platform* for ablation.

---

## What Else Is Feasible in ~5 Weeks

**Option A (the pivot you proposed):** Capability separation + component ablation. Probably the strongest story. Requires: task design (1 week), runs (1–2 weeks), ablations (1 week), writing (1 week). Very tight but feasible if tasks are chosen well and runs are parallelized.

**Option B: Narrow RMCA to one clean positive result.** Pick one task where RMCA wins (you need to find it — your W12 agenda item), prove it theoretically, ablate the key component. Submit a narrower but complete paper. Risk: you don't yet know if such a task exists.

**Option C: Pure theoretical paper.** Prove separation results (which model classes cannot solve which formal languages) for the SSM/gated-RNN tier where theory is thin. This is 2–3 people and requires someone with formal complexity theory background. If you have that, it's high-impact and doesn't require any new experiments.

**Option D: Short paper / findings paper.** Submit the comparative benchmark as a findings paper (some venues accept this, not NeurIPS main track). Lower bar, gets the results out, sets up a follow-up.

---

## My Honest Assessment

The pivot makes sense **if** you commit to Option A fully and don't try to preserve the RMCA-as-new-architecture narrative. The two framings are in tension: the capability separation paper uses RMCA as one data point in a spectrum, not as the protagonist.

The **formal languages angle** is the right differentiator from FLA/Zoology/Mamba papers. It gives you theoretical grounding (Chomsky hierarchy is known, model-theoretic results exist for Transformers, gap exists for SSMs), maps cleanly to your model hierarchy, and produces results that are hard to dismiss as cherry-picked benchmarks.

The main question before committing: **do you have or can you quickly build the formal language evaluation infrastructure?** If yes, Option A with formal languages + MQAR is the move. If not, the timeline gets tighter.

What's your current state on the code side — do you have a framework where swapping models on new tasks is fast, or is each new baseline a multi-day integration?

---

