# Noisy AR experiment

Tests whether RMM's intra-segment attention helps filter distractor tokens
out before writing to recurrent state, vs token-level GDN which must
absorb every token into a rank-1 state update.

## Data layout

Context = random shuffle of `N` KV pairs (`!K:V!`, 7 chars each) and
`K = N*D / B` noise blocks (`B` chars each), where:

- `D` = `distractors_per_kv` (avg noise chars per pair)
- `B` = `noise_block_size` (contiguous chunk size, default 1)

When `B = 7` (the KV-pair size), every unit in the context is 7 chars
long. Setting `tokens_per_segment = 7` then guarantees every model
segment contains **either one KV pair or one noise block, never both**
— eliminating the cross-segment-write artefact.

When `B = 1`, distractors are per-character (standard Noisy-AR).

Output dirs:
- `B=1`: `./data/N{N}-K2V2-V62_D{D}_1M`
- `B>1`: `./data/N{N}-K2V2-V62_D{D}_B{B}_1M`

## Order of operations

1. Build datasets (idempotent):
   ```
   bash 00_build_data.sh               # B=1 (default)
   B=7 bash 00_build_data.sh           # block-aligned to KV-pair size
   ```
2. Inspect what training will see:
   ```
   python inspect_noisy_data.py ./data/N4-K2V2-V62_D32_B7_1M -t 7 -n 3
   ```
   Colour-codes KV / noise / struct / query / target across segments
   and reports `mixed` segment count.
3. Pick a runner. Each iterates `N_PAIRS × D × LR × SEEDS`, skipping
   existing run dirs:
   - `run_gdn_noisy.sh` — token-level GatedDeltaNet baseline.
   - `run_armt_noisy.sh` — segment-level ARMT (1 pair/seg, M∈{4,8}).
   - `run_rmm_v5p4_noisy.sh` — RMM v5p4 pool/unpool, M∈{4,8},
     pps∈{1, N}.
   Override grid via env: `SEEDS="1"`, `N_PAIRS_LIST="8"`, `D_LIST="32"`,
   `B=7`, `MODES="1"` (RMM only).
4. Outputs land in `./runs-noisy-ar/<dataset>/<run-name>/run_{seed}/`.
5. Collect metrics via `notebooks/collect_results_rmmv5.ipynb`
   (path adjustment may be needed; see TODO).

## Segmentation arithmetic

KV-pair size = 7 (K=V=2 → `!K:V!`).

| config                | per-segment tokens | clean alignment? |
|-----------------------|--------------------|-----------------|
| `B=1, pps=1`          | `7 + D`            | no (per-char noise) |
| `B=7, pps=1, tps=7`   | `7`                | **yes** — every seg is pure-noise or pure-KV |
| `pps=N, tps=N*(7+D)`  | whole context      | n/a (single seg) |

## TODO

- OOD eval (train on `D=32`, evaluate on `D=128`). Needs a small
  eval-only wrapper for v5p4 — defer until matched-D runs return.
- Hook `notebooks/collect_results_rmmv5.ipynb` to scan `runs-noisy-ar/`.
