# TODO until ARR submission (deadline 2026-05-25, ~3.5 days)

Source of truth for what is left. Updated 2026-05-22 after restructuring
paper/latex/main.tex into the interpolation-narrative + 5-table version.

## Paper status

Restructured `paper/latex/main.tex` now contains:
- Abstract framed as "RMM = interpolation of token-level + segment-level,
  retains strengths of both".
- §3.4 "Where RMM Sits" with **Table 1** (architectural-position cost table)
  --- analytic, **no compute needed**.
- §4 Experiments split into 5 numbered subsections, each with a table:
  - **Table 2 (E1)** — main AR collapse + recovery across N∈{4,8,16,32}.
  - **Table 3 (E2)** — C×R disentanglement at N=8.
  - **Table 4 (E3)** — binding-writer ablation at M=1.
  - **Table 5 (E4)** — Noisy AR (deliberation).
  - **Table 6 (E5)** — two-form efficiency.
- Figure 1: `images/RMM vertical.png` placed in §3.3 with full caption.

Every placeholder is marked `\textsc{tbd}`; numbers already in `notebooks/
best.csv` have been pasted in. Goal: replace every TBD by submission.

## What is already in best.csv (no new compute required)

- Table 1 (analytic) — no data needed; just verify formulas.
- Table 2 / E1 token-level baselines: GDN, Mamba, Mamba2 at N=4/8/16/32 ✓.
- Table 2 / E1 segment baselines: ARMT M=1, RMT M=1 at N=4/8/16 ✓ (N=32: gap).
- Table 2 / E1 RMM-pool at N=4 (99.24) and N=8 (98.94) ✓.
- Table 3 / E2 ss=32 dv=128 row partial ✓ (M=2,4,8 cells from rmmv5p4).
- Table 4 / E3 "identity (M=T)" upper bound row ✓ (use GDN ss=32 ck4 numbers).
- Table 4 / E3 pool M=1 row ✓ (11.2 at N=8).

## What is still missing (priority-ordered)

### P0 — Required to fill the tables (ship-blocking)

1. **Plot/extract** Table 2/3/4 cells from existing tfevents → `best.csv`.
   Action: rerun `notebooks/collect_results_rmmv5.ipynb`. Then add a
   `make_paper_tables.py` that reads best.csv and emits LaTeX rows.
   Owner: data wrangling. ETA: 0.5 day.

2. **Self-attention writer** (`run_rmm_on_kv_retrieval-v5p7.py` +
   `modeling_rmt/huggingface_rmm_v5p7.py`). One intra-segment self-attn over
   h\' before the pool. Add via copying v5p6 and inserting a single
   `nn.MultiheadAttention` call inside `MemoryCompress` (pre-pool).
   Train at M=1 on N=8 and N=16. Fills Table 3 (E3) row 2 and Table 5 (E4)
   self-attn rows.
   ETA: 0.5 day code + 0.5 day compute.

3. **Noisy AR dataset generation.** `kv_dataset_utils.generate_sequence`
   already injects random characters between KV pairs via
   `min_segment_len` / `max_segment_len`. Build datasets:
   `data/N{4,8}-K2V2-V62_1M_D{32,128}/` with controlled distractor density
   (use a script: `scripts/build_noisy_ar.py` that calls the existing
   generator with the desired min/max segment len).
   Fills Table 5 (E4) inputs.
   ETA: 0.5 day.

4. **Train Noisy-AR runs**: GDN + RMM-pool + RMM-self-attn × N∈{4,8} ×
   train-D=32, eval-D∈{32,128}. Reuse `run_fla_on_kv_retrieval-default.py`
   and v5p7. 6–8 cells, ~6h each ⇒ overnight.
   ETA: 1 day compute (parallel on the 2× A100).

5. **Two-form efficiency micro-benchmark.** Standalone
   `scripts/bench/run_efficiency.py`: load each model at matched params,
   fixed context L·T=1024, time prefill and per-token decode with
   `torch.cuda.Event`, log `torch.cuda.max_memory_allocated`. Output a CSV
   row per (model, mode). Skip FLOPs (use analytic + param count).
   Fills Table 6 (E5).
   ETA: 0.5 day.

### P1 — Strongly desired, only if P0 finishes on schedule

6. **v5p4 ↔ v5p6 reproducibility check**: one config (N=8 M=4 ss=32 tps=7),
   1 seed, on v5p6 codepath. If numbers match, switch the paper's E1/E2 RMM
   rows to v5p6; otherwise note the gradient-horizon caveat in Limitations.
   ETA: 0.25 day compute.

7. **N=16 binder follow-up**: if self-attn writer recovers at N=8, immediately
   train at N=16. The N=16 column of Table 3 is currently the weakest part of
   the story.
   ETA: 0.5 day compute.

### P2 — Cut from submission; mention as future work

- Recursive-GDN writer ("two-scale GDN") — Table 4 row 4 stays \textsc{tbd}
  → cite as future work in §6.
- Bilinear writer — Table 4 row 3 stays \textsc{tbd} → same.
- Variable-segment training (one weight set, both interpolation endpoints) →
  already mentioned in Limitations.
- Diagonal-batching parallel-form vs ARMT direct comparison → cite
  Kuzmin 2026, no head-to-head.
- N=32 RMM run → leave blank, the row in Table 2 is honest as-is.

## Day-by-day calendar (3.5 days)

- **D-3.5 (today)**: P0.1 (best.csv refresh + Latex table extractor), P0.3
  (Noisy-AR data build script), launch P0.2 self-attn writer training.
- **D-2.5**: monitor P0.2 + launch P0.4 (Noisy-AR runs overnight). Start
  P0.5 efficiency micro-benchmark.
- **D-1.5**: collect P0.2, P0.4, P0.5 outputs; replace every \textsc{tbd} in
  main.tex. Run P1.6 reproducibility check in parallel.
- **D-0.5**: figure polish, bibliography pass, abstract tightening, page-limit
  check. ARR upload.

## Definition of done

- All 6 tables in main.tex have non-TBD values for the rows we commit to.
- Page count ≤ 4 (short paper) plus refs + limitations + appendix budget.
- Figure 1 caption matches the actual scheme used in the model.
- `paper/latex/main.tex` compiles clean (run `pdflatex` twice + `bibtex`).
- `notebooks/best.csv` regenerated from latest tfevents and committed.

