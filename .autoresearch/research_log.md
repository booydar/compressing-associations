# Research Log

Started: (will be filled by autoresearch.py on first run)

Format per entry:
## Iter N — [kept | reverted | baseline | failed] — EM: X.XXXX (N=K)
**Hypothesis:** ...
**Wall time:** X.X min
**Result:** EM=X.XXXX vs prev best=X.XXXX
**Rationale:** ...

---
## Iter 0 — kept — EM: 0.2676 (N=2)
**Hypothesis:** baseline — exact copy of v2
**Wall time:** 9.3 min
**Result:** EM=0.2676 vs prev best=-1.0000


## Iter 1 — FAILED — N=2
**Error:** planner error: Planner returned invalid JSON: Expecting value: line 1 column 1 (char 0)
Raw response:



## Iter 2 — FAILED — N=2
**Error:** planner error: Planner returned invalid JSON: Expecting value: line 1 column 1 (char 0)
Raw response:



## Iter 3 — FAILED — N=2
**Error:** planner error: Planner returned invalid JSON: Expecting value: line 1 column 1 (char 0)
Raw response:



## Iter 4 — FAILED — N=2
**Error:** planner error: Planner returned invalid JSON: Expecting value: line 1 column 1 (char 0)
Raw response:



## Iter 5 — FAILED — N=2
**Error:** planner error: Planner returned invalid JSON: Expecting value: line 1 column 1 (char 0)
Raw response:



## Iter 6 — FAILED — N=2
**Error:** sanity check failed: Expected class 'RMCABase' not found after modification


## Iter 7 — kept — EM: 0.2698 (N=2)
**Hypothesis:** Adding a learnable temperature parameter to the cross-attention softmax will sharpen attention distributions and improve exact-match retrieval accuracy.
**Wall time:** 26.7 min
**Result:** EM=0.2698 vs prev best=0.2676
**Rationale:** Softer attention distributions cause the model to distribute probability mass across multiple memory slots, reducing confidence in correct selections. Sharper attention (via temperature scaling) concentrates probability on the most relevant slot, which is critical for exact-match accuracy in associative retrieval tasks.


