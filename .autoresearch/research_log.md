# Research Log

Started: Apr 8, 2026

## Iter 108 — kept — EM: 0.9468 (N=2)
**Hypothesis:** Implementing a memory compression mechanism that selectively updates high-salience memory tokens will improve information retention for associative retrieval by preventing information dilution across memory slots.
**Wall time:** 34.3 min
**Result:** EM=0.9468 vs prev best=0.2816
**Rationale:** All 10 human-directed hyperparameter suggestions (n_mem_tokens, n_layer, n_head, n_embd, lr, optimizer, batch_size, max_steps, weight_decay, warmup ratios) have been attempted with values tried, reverted, or failed, yet best EM remains at 0.2816 from iter_083. With hyperparameter space exhausted and no architectural changes attempted yet, architectural intervention is now justified per the hyperparameter-first policy.

---
