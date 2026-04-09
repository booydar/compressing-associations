# Research Log

**Reference:** Previous successful run - iter_108 achieved EM=0.9468 at N=2 (Apr 8, 2026) using memory compression mechanism.

**New Start:** Beginning fresh autoresearch at N=4. Previous N=2 results archived for reference.

---
Started: Apr 9, 2026 (N=4)
## Iter 0 — kept — EM: 0.2528 (N=4)
**Hypothesis:** baseline — exact copy of v2
**Wall time:** 48.4 min
**Result:** EM=0.2528 vs prev best=-1.0000


## Iter 1 — reverted — EM: 0.0064 (N=4)
**Hypothesis:** The baseline learning rate may be suboptimal for the associative retrieval task, and systematic LR exploration will reveal a more effective training regime.
**Wall time:** 6.8 min
**Result:** EM=0.0064 vs prev best=0.2528
**Rationale:** Human direction #1 explicitly prioritizes systematic training hyperparameter exploration, and no hyperparameters have been tested yet (only baseline with EM=0.2528). Per HYPERPARAMETER-FIRST POLICY, I must exhaust hyperparameter tuning before architectural changes.


## Iter 2 — reverted — EM: 0.0058 (N=4)
**Hypothesis:** A systematic learning rate search with proper warmup and cosine decay will stabilize training for the associative retrieval task.
**Wall time:** 6.3 min
**Result:** EM=0.0058 vs prev best=0.2528
**Rationale:** Human direction #1 (training hyperparameter exploration) is still PENDING and takes absolute priority. Previous LR exploration (iter 1) was reverted; we need systematic exploration across 5e-5 to 3e-4 with cosine decay and adequate warmup. No architectural changes proposed as hyperparameter tuning must be exhausted first per rules.


## Iter 3 — reverted — EM: 0.0048 (N=4)
**Hypothesis:** Systematic batch size exploration will reveal the optimal gradient stability regime for associative retrieval, as prior LR changes failed to address capacity constraints.
**Wall time:** 11.3 min
**Result:** EM=0.0048 vs prev best=0.2528
**Rationale:** Following human direction #1 priority (training hyperparameters), I am exploring batch size since learning rate has already been tested in iterations 1-2 with poor EM results (0.0064, 0.0058). Larger batch sizes may improve gradient stability for the memory attention mechanism required in associative retrieval tasks.


