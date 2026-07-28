# v6p6-unified — one weight set, both modes

Nothing here is running. Review, then `./launch_v6p6_workers.sh stage1`.

All runs write under `runs-rebuttal/` so the trees backing published numbers are
never touched.

---

## What the existing data actually says

### 1. The v6p6 sweep already ran, at N16 / tps=7 / H=1 / ss32 / cap32

| M | lr | EM | tokacc | step | note |
|---|---|---|---|---|---|
| 7 (=T) | 3e-04 | 50.94 | 70.95 | 198.5k | still climbing (43.7 → 50.9 over last 58k) |
| 7 | 1e-04 | 44.60 | 66.51 | 195k | escaped ~100k, steeper slope than lr3e-4 |
| 7 | 1e-03 | 24.14 | 51.33 | 161.5k | |
| 4 | 3e-04 | 0.10 | 1.48 | 169k | **flat 0.0 for the entire run** |
| 4 | 1e-04 | 0.10 | 1.77 | 83k | |

So: identity-as-M==T reaches ~51 and is still climbing; compression to M=4 never
escapes chance in 169k steps.

### 2. There is no matched control for those numbers

Every v5p7 identity run at N16 is `tps=112 / pps=16` — the whole 16-pair context in
**one** segment. `grep runs-rmmv5p7/N16-*`: zero identity runs at tps=7. The
compressed cells (v5p4 unpool→pool, 55.08) are all tps=7, i.e. 16 segments.

Table 2's "identity 98.5 vs compressed 55.1" therefore varies **model, compression
ratio, and segmentation simultaneously**. That is the reviewer-facing weakness, and
v6p6 is the only version that can close it, because identity is not a mode here —
it is `num_memory_vectors == T`, selected by omitting the flag, at any `tps`, from
one weight set.

This reframes the tps=7 result: 50.94 is not a regression against 98.5, because
those two numbers were never comparable.

### 3. EM ≈ tokacc² everywhere — watch token_accuracy

| run | EM | tokacc | tokacc² |
|---|---|---|---|
| v6p6 M7 lr3e-4 | 50.94 | 70.95 | 50.3 |
| v6p6 M7 lr1e-4 | 44.60 | 66.51 | 44.2 |
| v6p4-armt M8 | 90.70 | 95.33 | 90.9 |
| v5p7 identity | 99.02 | 99.51 | 99.0 |

The two value tokens fail **independently**. The ~50 plateau is uniform partial
retrieval, not a dropped position — so there is no positional bug to hunt, and a
cell at 71% tokacc is much closer to solved than its 51% EM suggests. EM squares
away the signal you need to call runs early. `collect_v6p6.py` reports both plus a
slope.

### 4. State size is fixed at 128 (`state_size=32`) in every script here

Raising it invalidates the GDN/mamba baselines without a re-run. The v6p0/p1/p2
99s came from an unintended ~786k/layer state and are not usable as evidence.

### 5. Bank capacity differs from the existing runs

The new scripts use `max_memory_vectors=112` (needed for M=T at tps=112); the
existing tps=7 runs used 32. The bank is sliced to `min(M, T)` so the active path is
identical, but the parameter count is not. Everything inside this grid is internally
consistent at cap=112 — only the ladder's borrowed tps=7 endpoint is not, and one
cheap re-run fixes that if the ladder shows a trend worth reporting.

### 6. Open confound, not addressed by this grid

`n_head`. On the v5p7 identity cell, H=1 → 97.96 and H=4 → 81.68, same everything
else. The v6p6 scripts use H=1; `run_v6p4armt_N16_seeds.sh` keeps H=4 deliberately,
so its new seeds stay comparable to the existing ones. Worth a footnote either way.

---

## The grid

### Stage 1 — gate

**`run_v6p6_N16_ctrl_1seg.sh`** — v6p6 at M=T, `tps=112`: the same segmentation as
the v5p7 identity cell that reached 97.96 / 99.02.

This is a **gate, not a result**. If it lands near 98, the unified path is sound and
the ratio curve below is meaningful. If it plateaus near 50 like the tps=7 runs did,
v6p6 has a defect, nothing downstream is interpretable, and the right move is to
debug rather than to spend the remaining GPU on stage 2.

**`run_v6p4armt_N16_seeds.sh`** — the hedge, runs concurrently, independent of v6p6.
v6p4-armt is the best N16 compressed cell among correct-state models: (90.70, 49.46)
at lr1e-4 and (91.54, 27.80) at lr3e-4. One good seed and one collapse per LR is the
beta_L0 write-gate-death signature, and with n=2 it is not reportable. Four more
seeds turns `70.08 ± 20` into "escapes k/6, reaching ~91 when it does".

### Stage 2 — the figure (gated on stage 1)

**`run_v6p6_N16_ratio_1seg.sh`** — M ∈ {32, 8, 4} at `tps=112`, identical to the ctrl
run in every other respect. Same weights, same code path, same state, same
segmentation; only M moves. With the ctrl as the M/T=1 anchor that is a 4-point
compression curve that no existing pair of runs can produce.

Prior: at tps=7, M=4 sat at exactly 0.0 for 169k steps. If compression fails
discontinuously rather than degrading, that is a sharper and more defensible claim
than 55.1.

**`run_v6p6_N16_seg_ladder.sh`** — M/T held at 1, `tps` ∈ {56, 28}. With ctrl
(tps=112, 1 segment) and the existing tps=7 run (16 segments, 50.94) that is a
5-point ladder isolating recurrence depth from compression. Lower priority than the
ratio curve; run it if there is time.

### Tooling

**`collect_v6p6.py`** — EM, tokacc, step, and Δtokacc/20k for every run in the
rebuttal roots. A nonzero slope means the cell has not converged and its number is a
lower bound; 200k already produced three truncation artifacts in Table 2.

**`extend_v6p6_run.py`** — resume-and-extend, generalised from `extend_pool_run.py`.
Reconstructs the command from the run's own `config.json`, stages to
`runs-rebuttal/rmmv6p6ext/` so the source is never written to. `lr_scheduler_type` is
`constant_with_warmup` in all these runs, so extension is a pure continuation.

Use it on the two M=7 arms that were stopped while still climbing — they are the
tps=7 endpoint of the ladder and are already paid for:

```
./extend_v6p6_run.py --dry --iters 400000 \
  runs-rmmv6p6/N16-K2V2-V62_1M/rmmv6p6_pool_llama_L4H1D128_ss32_cap32_M7_lr3e-04_bs64_tps7_id_init/run_1 \
  runs-rmmv6p6/N16-K2V2-V62_1M/rmmv6p6_pool_llama_L4H1D128_ss32_cap32_M7_lr1e-04_bs64_tps7_id_init/run_1
```

Extending an arm that plateaus near 50 will not produce 98 — this firms up a rung,
it does not substitute for the ctrl run. Verified: `--dry` reconstructs both commands
correctly and stages nothing. Paths must be **repo-relative** — the script `chdir`s
to the repo root before resolving them.

Both arms are measurably unconverged — `collect_v6p6.py` puts them at **+2.2** and
**+2.9** tokacc per 20k steps at 198.5k / 195k.

**Prerequisite:** `run_rmm_on_kv_retrieval-v6p6.py` has no `checkpoint` field and
calls `trainer.train()` with no arguments, so it cannot resume at all.
`v6p6_add_resume.patch` is the two hunks needed, copied verbatim from
`run_rmm_on_kv_retrieval-v5p4.py` (lines 258–260 and 463–470). It is a **hand-apply
guide, not a `git apply`-able diff** — it has no line context. `extend_v6p6_run.py`
greps for the field and refuses to run until it is there.

---

## Running it

```bash
cd scripts/assoc-comp-rmm-rebuttal/v6p6-unified
chmod +x *.sh *.py

./launch_v6p6_workers.sh status      # confirm both GPUs are free
./launch_v6p6_workers.sh stage1      # 6 workers, 1 run each
nvidia-smi dmon -s u -c 60           # check SM% before adding more
./launch_v6p6_workers.sh readout     # EM / tokacc / slope

# only after ctrl reaches ~98:
./launch_v6p6_workers.sh stage2
```

### Packing

You have been running 2 per GPU. These are ~1–2M-param models at batch 64, so they
are launch-bound rather than compute-bound and pack further — `launch_N32_workers.sh`
already notes 2 jobs reaching only 50–85% and puts the ceiling at 3–4. Split by
segmentation:

- **tps=7** (armt hedge, extends): 16 sequential 7-token segments, almost pure launch
  overhead → **4 per GPU**.
- **tps=112** (ctrl, ratio, ladder): one segment with parallel prefill, denser kernels
  → **3 per GPU**.

Stage 1 is laid out on that basis: 3 tps=112 jobs on GPU0, 3 tps=7 jobs on GPU1.
Verify rather than trusting it — `nvidia-smi dmon -s u -c 60`, and if sustained SM%
is below ~70 add a worker with the one-liners printed by `launch_v6p6_workers.sh`
with no argument. Past saturation, throughput is conserved: extra jobs delay every
result equally, including the gate.

Every script skips run directories that already exist, so re-running a worker after a
crash resumes the queue rather than clobbering finished cells.
