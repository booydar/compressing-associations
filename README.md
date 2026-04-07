# Autoresearch — RMCA on Associative Retrieval

Autonomous research loop that iteratively improves the RMCA model architecture on the associative retrieval (KV-lookup) benchmark. An LLM planner proposes architectural changes; an LLM executor implements them; short experiments measure whether EM improved.

---

## What this does

The loop runs up to N iterations:

1. **Planner** reads the research history and proposes a hypothesis (JSON).
2. **Executor** reads the hypothesis and current model file, returns a modified model file.
3. **Sanity check** — syntax + import validation, no GPU needed.
4. **Experiment** — trains for ≤5000 steps with early stopping.
5. **Eval** — reads `all_results.json` → `eval_exact_match`.
6. If EM improved: keep the change. Else: `git checkout` reverts the model file.
7. Records result in `results_memory.json` and appends a paragraph to `research_log.md`.
8. If EM ≥ 0.99 on current N: advances to next N-level (N=2 → N=4 → N=8 …).

The loop is a plain Python `for` loop. No framework. No background processes required.

---

## Repository layout

```
.autoresearch/              infrastructure (do not modify by hand during a run)
  autoresearch.py           main loop
  planner.py                planner agent — history → JSON hypothesis
  executor.py               executor agent — hypothesis + model → modified model
  llm_client.py             unified LLM client (Anthropic / OpenAI / local / Cursor)
  eval_harness.py           reads all_results.json → exact_match float
  config.yaml               all settings and LLM provider config
  .env.template             API key template — copy to .env and fill in
  program.md                current objective, N-level, best EM (auto-updated)
  research_log.md           human-readable append-only log (one paragraph per iter)
  results_memory.json       structured history, capped at 50 entries
  conventions.md            repo map passed to LLM agents as context

modeling_rmt/
  huggingface_rmca_v2.py   original RMCA — do not modify
  huggingface_rmca_v3.py   agent-editable copy — modified in-place each iteration

run_rmca_on_kv_retrieval-v3.py   trainer that imports from v3

scripts/
  run_autoresearch_exp.sh  short-run launcher called by autoresearch.py
  test_rmca.sh             quick manual smoke test

runs-autoresearch/         raw experiment outputs (TensorBoard, checkpoints)
  n2/iter_000_baseline/
  n2/iter_001/
  ...
```

---

## Setup

### 1. Install Python dependencies

```bash
pip install anthropic openai pyyaml python-dotenv
```

### 2. Configure API keys

```bash
cp .autoresearch/.env.template .autoresearch/.env
# edit .autoresearch/.env — add your keys
```

Keys needed only for the providers you actually use. Local models (LMStudio, llama.cpp) and the Cursor bridge require no key.

### 3. Configure LLM providers

Edit `.autoresearch/config.yaml`. The `llm.planner` and `llm.executor` blocks control which model is used for each role. Four provider types are supported:

| Provider | When to use |
|---|---|
| `anthropic` | Claude models via Anthropic API |
| `openai` | GPT models via OpenAI API |
| `local` | Any OpenAI-compatible local server (LMStudio, llama.cpp) |
| `cursor` | All Cursor subscription models via cursor-openai-bridge |

**Example: use Claude for planning, local model for execution**

```yaml
llm:
  planner:
    provider: anthropic
    model: claude-opus-4-5
    api_key_env: ANTHROPIC_API_KEY

  executor:
    provider: local
    model: unsloth/Qwen3.5-27B-Q6K
    host: 127.0.0.1
    port: 8117          # llama.cpp server port
```

**Local model options** (from `~/.opencode/opencode.json`):

- LMStudio: `host: 127.0.0.1`, `port: 1234` — models: `qwen3.5-9b`, `qwen_qwen3.5-27b@q4_k_m`, `openai/gpt-oss-20b`
- llama.cpp: `host: 127.0.0.1`, `port: 8117` — models: `unsloth/Qwen3.5-27B-Q6K`, `bartowski/Qwen_Qwen3.5-27B-GGUF`

**Cursor bridge** — exposes all Cursor subscription models (Claude, Gemini, GPT-4o, etc.) as a local OpenAI-compatible API at no extra cost:

```bash
# Build once:
cd /Users/bulatov/Desktop/projects/opencode/tools/cursor-opencode-auth/packages/cursor-openai-bridge
npm run build

# Start before running autoresearch (or set auto_start: true in config.yaml):
node dist/cli.js
```

Then in `config.yaml`:

```yaml
llm:
  planner:
    provider: cursor
    model: claude-opus-4-5
    host: 127.0.0.1
    port: 8765
```

### 4. (Optional) Test connections

```bash
python .autoresearch/test_connections.py
```

Probes every configured provider plus both local servers (regardless of config), prints `[OK]` / `[FAIL]` with timing.

### 5. Ensure data exists

The trainer expects data at `./data/N{N}-K{K}V{V}-V62_1M/`. For N=2 the path is `./data/N2-K2V2-V62_1M/`. Generate or symlink datasets before starting.

---

## Run

```bash
python .autoresearch/autoresearch.py
```

Iteration 0 is always a baseline run (no model changes). From iteration 1 onward the loop proposes and applies changes.

To resume after an interruption, just re-run the same command — `iter_start` is set from the length of `results_memory.json`, so no iterations are re-run.

---

## Monitoring during a run

| What | Where |
|---|---|
| Console progress | stdout — one block per iteration, shows hypothesis, EM, verdict |
| Human-readable summary | `.autoresearch/research_log.md` — open this in an editor |
| Current objective/best | `.autoresearch/program.md` |
| Structured history | `.autoresearch/results_memory.json` |
| Raw TensorBoard logs | `runs-autoresearch/n{N}/iter_{i}/` |

---

## Key settings (`config.yaml`)

```yaml
experiment:
  max_iters: 50           # total iterations to run
  max_steps: 5000         # training steps per experiment
  early_stopping_patience: 20   # stop if no EM improvement for this many evals
  n_start: 2              # starting N-level
  em_threshold: 0.99      # EM required to advance to next N
  batch_size: 64          # per-device = total (NP=1)
  lr: 3e-4

git:
  auto_commit: true       # commit after each iteration
```

---

## Model file

The agent modifies `modeling_rmt/huggingface_rmca_v3.py` in-place. On a failed experiment it is restored via `git checkout`. Key classes:

- `RMCAConfig` — model hyperparameters
- `MemoryAugmentedLayer` — wraps a transformer layer with memory read/write cross-attention
- `RMCACell` — full model with memory layers
- `RMCABase` — top-level HF model (do not rename)

See `.autoresearch/conventions.md` for the full data flow and what must not be changed.
