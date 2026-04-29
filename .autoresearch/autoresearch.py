"""
Autoresearch main loop.

Usage (from repo root):
    python .autoresearch/autoresearch.py

Requirements:
    pip install anthropic openai pyyaml python-dotenv

The loop:
  iter 0  : baseline — run v3 (exact copy of v2), record EM
  iter 1+ : planner → hypothesis → executor → new model → run → eval
            if EM improved: keep, else revert
  Each iteration appends to results_memory.json and research_log.md.
  When EM >= em_threshold on current N, N is advanced.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Parse stream ID from command line BEFORE any imports
_STREAM_ID_ARG = None
for i, arg in enumerate(sys.argv):
    if arg == "--stream-id" and i + 1 < len(sys.argv):
        _STREAM_ID_ARG = sys.argv[i + 1]
        break

# Set environment variable early so planner/executor modules read it correctly
if _STREAM_ID_ARG:
    os.environ["AUTORESEARCH_STREAM_ID"] = _STREAM_ID_ARG

# resolve repo root (parent of .autoresearch/)
REPO_ROOT = Path(__file__).resolve().parent.parent
AUTORESEARCH_DIR = REPO_ROOT / ".autoresearch"

sys.path.insert(0, str(AUTORESEARCH_DIR))

from eval_harness import get_metrics
from planner import plan, plan_with_trace_full, parse_human_directions
from executor import execute, execute_with_trace_full, _validate_yaml

# Shared files (common across all streams)
SHARED_MODEL_FILE = None  # set in main() from config["model_file"]
SHARED_PROGRAM_MD = AUTORESEARCH_DIR / "program.md"
RESEARCH_LOG = AUTORESEARCH_DIR / "research_log.md"
MEMORY_FILE = AUTORESEARCH_DIR / "results_memory.json"
CONFIG_FILE = AUTORESEARCH_DIR / "config.yaml"
SHARED_EXPERIMENT_CONFIG_FILE = AUTORESEARCH_DIR / "experiment_config.yaml"
HUMAN_DIRECTIONS_FILE = AUTORESEARCH_DIR / "human_directions.md"
EXPERIMENT_QUEUE_FILE = AUTORESEARCH_DIR / "experiment_queue.json"
CONVENTIONS_FILE = AUTORESEARCH_DIR / "conventions.md"
SUMMARY_FILE = AUTORESEARCH_DIR / "experiment_summary.md"
SHARED_ARTIFACTS_DIR = AUTORESEARCH_DIR / "artifacts"
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_autoresearch_exp.sh"

# Stream-specific paths (set during initialization)
STREAM_DIR = None
STREAM_MODEL_FILE = None
STREAM_CONFIG_FILE = None
STREAM_PROGRAM_MD = None
STREAM_ARTIFACTS_DIR = None
STREAM_RUNS_DIR = None
STREAM_ID = "0"
HUMAN_DIRECTION_STATUS_RE = re.compile(
    r"^(?P<number>\d+)\.\s+\[(?P<status>Pending|Running|Done|Failed|Skipped)\]",
    re.MULTILINE,
)


# ── cursor bridge ─────────────────────────────────────────────────────────────

def _cursor_bridge_alive(host: str, port: int) -> bool:
    """Return True if the cursor-openai-bridge health endpoint responds."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _ensure_cursor_bridge(cfg: dict) -> None:
    """
    If any configured provider is 'cursor', check that the bridge is reachable.
    If auto_start is true, launch it as a background process first.
    """
    bridge_needed = any(
        v.get("provider") == "cursor"
        for v in [cfg["llm"].get("planner", {}), cfg["llm"].get("executor", {})]
        if isinstance(v, dict)
    )
    if not bridge_needed:
        return

    bridge_cfg = cfg.get("cursor_bridge", {})
    host = bridge_cfg.get("host", "127.0.0.1")
    port = bridge_cfg.get("port", 8765)

    if _cursor_bridge_alive(host, port):
        print(f"[bridge] cursor-openai-bridge already running on {host}:{port}")
        return

    if bridge_cfg.get("auto_start"):
        bin_path = bridge_cfg.get("bin")
        if not bin_path or not Path(bin_path).exists():
            raise RuntimeError(
                f"cursor-openai-bridge binary not found at {bin_path!r}.\n"
                "Build it first: cd <bridge_dir> && npm run build\n"
                "Or set auto_start: false and start it manually."
            )
        workspace = bridge_cfg.get("workspace", str(REPO_ROOT))
        env = os.environ.copy()
        env["CURSOR_BRIDGE_HOST"] = host
        env["CURSOR_BRIDGE_PORT"] = str(port)
        env["CURSOR_BRIDGE_WORKSPACE"] = workspace
        print(f"[bridge] starting cursor-openai-bridge on {host}:{port}...")
        subprocess.Popen(
            ["node", bin_path],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give it 5s to start
        for _ in range(10):
            time.sleep(0.5)
            if _cursor_bridge_alive(host, port):
                print(f"[bridge] cursor-openai-bridge is up")
                return
        raise RuntimeError(
            f"cursor-openai-bridge did not respond on {host}:{port} after 5s.\n"
            "Check that the bridge binary is built and the Cursor agent binary is in PATH."
        )
    else:
        raise RuntimeError(
            f"cursor provider is configured but cursor-openai-bridge is not running "
            f"on {host}:{port}.\n"
            f"Start it manually: node {bridge_cfg.get('bin', '<bridge_bin>')}\n"
            "Or set cursor_bridge.auto_start: true in config.yaml."
        )


# ── helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        cfg = yaml.safe_load(f)
    env_file = REPO_ROOT / cfg.get("env_file", ".autoresearch/.env")
    if env_file.exists():
        _load_dotenv(env_file)
    return cfg


def load_experiment_config() -> dict:
    with open(STREAM_CONFIG_FILE) as f:
        return yaml.safe_load(f)


def save_experiment_config(exp_cfg: dict) -> None:
    with open(STREAM_CONFIG_FILE, "w") as f:
        yaml.dump(exp_cfg, f, default_flow_style=False, sort_keys=False)


def update_human_directions_status(item_number: str, new_status: str) -> bool:
    """Update a numbered human_directions item status in place."""
    if not HUMAN_DIRECTIONS_FILE.exists():
        return False

    content = HUMAN_DIRECTIONS_FILE.read_text()
    pattern = rf"^({re.escape(item_number)}\.\s+)\[(Pending|Running|Done|Failed|Skipped)\]"
    new_content, count = re.subn(pattern, rf"\1[{new_status}]", content, count=1, flags=re.MULTILINE)
    if count:
        HUMAN_DIRECTIONS_FILE.write_text(new_content)
        print(f"[human_directions] marked item #{item_number} as [{new_status}]")
        return True
    return False


def update_human_directions_completed(item_number: str) -> bool:
    return update_human_directions_status(item_number, "Done")


def _load_dotenv(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return _read_memory_locked()
    return {
        "current_best": {"variant": "none", "em": -1.0, "n_level": 0},
        "n_level": None,
        "experiments": [],
    }


def _merge_memory_for_save(our_memory: dict) -> dict:
    """Merge our in-memory state with on-disk state from other streams.

    Entries belonging to our stream (matching stream_id) overwrite the file.
    Entries from other streams are preserved. Entries without stream_id
    (pre-migration) are preserved as-is.
    """
    if not MEMORY_FILE.exists():
        return our_memory

    try:
        on_disk = _read_memory_locked()
    except (FileNotFoundError, json.JSONDecodeError):
        return our_memory

    # Build lookup: (stream_id, id) -> entry for both our memory and on-disk
    # For entries without stream_id, use exp_path to infer ownership
    our_stream = STREAM_ID

    def _entry_key(e):
        sid = e.get("stream_id")
        if sid is not None:
            return (sid, e["id"])
        # Pre-migration entry: infer from exp_path or mark as unowned
        exp_path = e.get("exp_path", "")
        if f"stream_{our_stream}" in exp_path:
            return (our_stream, e["id"])
        return ("__unowned__" + str(e.get("started_at", 0)), e["id"])

    on_disk_map = {(_entry_key(e), i): e for i, e in enumerate(on_disk.get("experiments", []))}
    our_map = {_entry_key(e): e for e in our_memory.get("experiments", [])}

    # Start with on-disk entries from other streams
    merged_experiments = []
    for (key, orig_idx), entry in sorted(on_disk_map.items(), key=lambda x: x[0][1]):
        if key in our_map:
            # Our stream's entry overrides
            merged_experiments.append(our_map[key])
        else:
            # Other stream's entry preserved as-is
            merged_experiments.append(entry)

    # Append our entries that don't exist in on-disk (new experiments)
    for key, entry in our_map.items():
        if key not in {k for k, _ in on_disk_map.keys()}:
            merged_experiments.append(entry)

    # Merge current_best: take the entry with highest EM across all streams
    all_entries = merged_experiments
    best_em = -1.0
    best_variant = "none"
    best_n = our_memory.get("n_level", 0)
    for e in all_entries:
        em = e.get("em_score")
        if isinstance(em, (int, float)) and em > best_em:
            best_em = em
            best_variant = e.get("iter_tag", f"iter_{e['id']:03d}")
            best_n = e.get("n_level", best_n)

    # Use the n_level from our memory (it may have advanced via threshold)
    merged = {
        "current_best": {
            "variant": our_memory["current_best"]["variant"],
            "em": our_memory["current_best"]["em"],
            "n_level": our_memory["current_best"]["n_level"],
        },
        "n_level": our_memory["n_level"],
        "experiments": merged_experiments,
    }

    # If our current_best isn't the global best, check on_disk's current_best
    if on_disk["current_best"]["em"] > merged["current_best"]["em"]:
        merged["current_best"] = on_disk["current_best"]
        # n_level may also need to come from on_disk if it advanced
        if on_disk["n_level"] > merged["n_level"]:
            merged["n_level"] = on_disk["n_level"]

    return merged


def save_memory(memory: dict) -> None:
    merged = _merge_memory_for_save(memory)
    _write_memory_locked(merged)


def load_program_md() -> str:
    return STREAM_PROGRAM_MD.read_text() if STREAM_PROGRAM_MD.exists() else ""


def update_program_md(n_level: int, current_best_em: float, best_variant: str, understanding: str = "") -> None:
    exp_cfg = load_experiment_config()
    _cfg = yaml.safe_load(CONFIG_FILE.read_text())
    model_file = _cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py")
    model_filename = Path(model_file).name
    content = f"""# Research Program (Stream {STREAM_ID})

## Objective
Maximize exact-match (EM) on associative retrieval task.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Target files: {model_file} (architecture) or .autoresearch/experiment_config.yaml (hyperparameters)
- No parameter count explosion (~50% max increase without strong justification)
- Max experiment length: {exp_cfg['max_steps']} steps

## Allowed Changes
- **Architecture**: Any modification to {model_filename} (layers, memory mechanisms, etc.)
- **Model hyperparameters**: n_layer, n_head, n_embd and model-specific params (in experiment_config.yaml)
- **Training hyperparameters**: lr, batch_size, warmup_steps, eval_steps, logging_steps, early_stopping_patience (in experiment_config.yaml)

## Current State
- Stream: {STREAM_ID}
- N-level: {n_level}
- Current best EM: {current_best_em:.4f}
- Best variant: {best_variant}
- Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Current Understanding
{understanding if understanding else '(updated each iteration by autoresearch loop)'}
"""
    STREAM_PROGRAM_MD.write_text(content)


def append_research_log(entry: str) -> None:
    _append_research_log_locked(entry)


def _artifact_dir(iter_tag: str) -> Path:
    return STREAM_ARTIFACTS_DIR / iter_tag


def _save_traces_to_artifacts(iter_tag: str, planner_trace: dict | None, executor_trace: dict | None) -> None:
    """Save planner and executor traces to the stream-specific artifacts folder."""
    artifact_path = _artifact_dir(iter_tag)
    artifact_path.mkdir(parents=True, exist_ok=True)

    if planner_trace is not None:
        planner_file = artifact_path / "planner_trace.json"
        with open(planner_file, 'w') as f:
            json.dump(planner_trace, f, indent=2, default=str)
        print(f"[traces] saved planner trace to {planner_file}")

    if executor_trace is not None:
        executor_file = artifact_path / "executor_trace.json"
        with open(executor_file, 'w') as f:
            json.dump(executor_trace, f, indent=2, default=str)
        print(f"[traces] saved executor trace to {executor_file}")

    if STREAM_MODEL_FILE and Path(STREAM_MODEL_FILE).exists():
        dest = artifact_path / Path(STREAM_MODEL_FILE).name
        shutil.copy2(STREAM_MODEL_FILE, dest)
        print(f"[traces] saved model snapshot to {dest}")

    if STREAM_CONFIG_FILE and Path(STREAM_CONFIG_FILE).exists():
        dest = artifact_path / "experiment_config.yaml"
        shutil.copy2(STREAM_CONFIG_FILE, dest)
        print(f"[traces] saved config snapshot to {dest}")


def _ensure_runtime_files() -> None:
    STREAM_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    if not RESEARCH_LOG.exists():
        RESEARCH_LOG.write_text(f"# Research Log\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    if not SUMMARY_FILE.exists():
        SUMMARY_FILE.write_text("# Experiment Summary\n\n")


def _append_experiment_summary(entry: dict, error_msg: str | None = None) -> None:
    if entry.get("summary_logged"):
        return

    hypothesis = entry.get("hypothesis") or {}
    verdict = entry.get("verdict", "unknown")
    em = entry.get("em_score")
    target = hypothesis.get("target_component", "(none)")
    rationale = hypothesis.get("rationale", "")
    exp_path = entry.get("exp_path", "(none)")

    if verdict in {"kept", "baseline", "recovered"}:
        success_line = f"Accepted outcome: {verdict}."
        weakness_line = "Weaknesses remain unclear from this iteration alone."
        failure_line = "No execution failure."
    elif verdict == "reverted":
        success_line = "Change ran successfully and produced a measurable result."
        weakness_line = "It did not improve over the previous best."
        failure_line = "No executor or run failure, but the hypothesis underperformed."
    else:
        success_line = "No model improvement established."
        weakness_line = "The experiment did not reach a valid kept result."
        failure_line = error_msg or entry.get("run_error") or "Failure details unavailable."

    block = (
        f"## Iter {entry.get('id', '?')} | {verdict} | N={entry.get('n_level', '?')}\n"
        f"- Hypothesis: {entry.get('description', '(none)')}\n"
        f"- Target: {target}\n"
        f"- EM: {f'{em:.4f}' if isinstance(em, (int, float)) else 'n/a'}\n"
        f"- Success: {success_line}\n"
        f"- Weaknesses: {weakness_line}\n"
        f"- Failures: {failure_line}\n"
        f"- Rationale: {rationale if rationale else '(none)'}\n"
        f"- exp_path: {exp_path}\n"
    )
    with open(SUMMARY_FILE, "a") as f:
        f.write(block + "\n")
    entry["summary_logged"] = True


def _create_iter_entry(
    memory: dict,
    iter_id: int,
    iter_tag: str,
    n_level: int,
    current_best_em: float,
    description: str,
    exp_path: str,
    hypothesis: dict | None = None,
    retry_of: int | None = None,
    status: str = "planning",
) -> dict:
    entry = {
        "id": iter_id,
        "iter_tag": iter_tag,
        "description": description,
        "hypothesis": hypothesis,
        "em_score": None,
        "prev_best": current_best_em,
        "verdict": status,
        "status": status,
        "n_level": n_level,
        "exp_path": exp_path,
        "wall_time_min": 0.0,
        "metric_step": None,
        "metric_source": None,
        "is_partial": False,
        "recovery_status": "pending",
        "needs_retry": False,
        "retry_of": retry_of,
        "run_error": None,
        "started_at": time.time(),
        "artifacts_dir": str(_artifact_dir(iter_tag)),
        "summary_logged": False,
        "stream_id": STREAM_ID,
    }
    memory["experiments"].append(entry)
    return entry


def _build_retry_tag(memory: dict, retry_of: int) -> str:
    retry_count = 1 + sum(1 for e in memory["experiments"] if e.get("retry_of") == retry_of)
    return f"iter_{retry_of:03d}_retry{retry_count}"


def _is_config_change_target(target: str) -> bool:
    return ".autoresearch/experiment_config.yaml" in target or "experiment_config.yaml" in target


def _record_running_iter(
    memory: dict,
    iter_id: int,
    iter_tag: str,
    n_level: int,
    current_best_em: float,
    description: str,
    exp_path: str,
    hypothesis: dict | None = None,
    retry_of: int | None = None,
) -> dict:
    entry = _create_iter_entry(
        memory=memory,
        iter_id=iter_id,
        iter_tag=iter_tag,
        n_level=n_level,
        current_best_em=current_best_em,
        description=description,
        exp_path=exp_path,
        hypothesis=hypothesis,
        retry_of=retry_of,
        status="running",
    )
    append_research_log(
        f"## Iter {iter_id} — RUNNING — N={n_level}\n"
        f"**Hypothesis:** {description}\n"
        f"**exp_path:** {exp_path}\n"
    )
    return entry


def _revert_entry_change(entry: dict) -> None:
    hypothesis = entry.get("hypothesis")
    if not hypothesis:
        return

    if _is_config_change_target(hypothesis.get("target_component", "")):
        git_revert_config()
    else:
        git_revert_model()


def _finalize_running_entry(
    memory: dict,
    exp_cfg: dict,
    entry: dict,
    metrics: dict,
    wall_time_min: float,
    run_error: str | None = None,
) -> tuple[str, float]:
    em = metrics["exact_match"]
    prev_best_em = entry.get("prev_best", memory["current_best"]["em"])
    current_best_em = memory["current_best"]["em"]
    is_baseline = entry["id"] == 0 and not entry.get("hypothesis")

    is_fix_base = (entry.get("hypothesis") or {}).get("_fix_base", False)
    if em > current_best_em:
        verdict = "kept"
        memory["current_best"] = {
            "variant": entry.get("iter_tag", f"iter_{entry['id']:03d}"),
            "em": em,
            "n_level": entry["n_level"],
        }
    elif is_fix_base:
        # Keep the fix unconditionally — a broken HEAD is worse than any EM regression
        verdict = "kept"
        memory["current_best"] = {
            "variant": entry.get("iter_tag", f"iter_{entry['id']:03d}"),
            "em": em,
            "n_level": entry["n_level"],
        }
    else:
        verdict = "reverted" if entry.get("hypothesis") else "baseline"
        if entry.get("hypothesis"):
            _revert_entry_change(entry)

    entry.update({
        "em_score": em,
        "prev_best": prev_best_em,
        "verdict": verdict if not is_baseline else "baseline",
        "status": "completed",
        "wall_time_min": round(wall_time_min, 1),
        "token_accuracy": metrics["token_accuracy"],
        "metric_step": metrics["step"],
        "metric_source": metrics["source"],
        "is_partial": metrics["is_partial"],
        "recovery_status": "recovered" if metrics["is_partial"] else "final",
        "run_error": run_error,
        "needs_retry": False,
    })

    return entry["verdict"], em


def _mark_entry_unresolved(entry: dict, error_msg: str, planner_trace: dict | None = None, executor_trace: dict | None = None) -> None:
    started_at = entry.get("started_at", time.time())
    wall_time_min = max(0.0, (time.time() - started_at) / 60)
    iter_tag = entry.get("iter_tag", f"iter_{entry.get('id', '?'):03d}")
    entry.update({
        "em_score": None,
        "verdict": "failed",
        "status": "failed",
        "wall_time_min": round(wall_time_min, 1),
        "metric_source": None,
        "is_partial": False,
        "recovery_status": "unresolved",
        "needs_retry": False,
        "run_error": error_msg,
    })
    append_research_log(
        f"## Iter {entry.get('id', '?')} — FAILED — N={entry.get('n_level', '?')}\n"
        f"**Error:** {error_msg}\n"
        f"**exp_path:** {entry.get('exp_path')}\n"
        f"**Recovery status:** unresolved\n"
        f"**Next action:** planner will propose new change based on error.\n"
    )
    _append_experiment_summary(entry, error_msg)
    _save_traces_to_artifacts(iter_tag, planner_trace, executor_trace)


def _reconcile_running_entries(memory: dict, exp_cfg: dict) -> tuple[int, int]:
    recovered = 0
    unresolved = 0

    for entry in memory["experiments"]:
        if entry.get("status") != "running":
            continue

        exp_path = entry.get("exp_path")
        if not exp_path:
            _mark_entry_unresolved(entry, "running entry is missing exp_path")
            unresolved += 1
            continue

        try:
            metrics = get_metrics(exp_path)
        except Exception as exc:
            _mark_entry_unresolved(entry, f"could not recover metrics from {exp_path}: {exc}",
                                   planner_trace=None, executor_trace=None)
            unresolved += 1
            continue

        started_at = entry.get("started_at", time.time())
        wall_time_min = max(0.0, (time.time() - started_at) / 60)
        verdict, em = _finalize_running_entry(memory, exp_cfg, entry, metrics, wall_time_min, entry.get("run_error"))
        description = entry.get("description", f"iter {entry['id']}")
        append_research_log(
            f"## Iter {entry['id']} — {verdict} — EM: {em:.4f} (N={entry['n_level']})\n"
            f"**Hypothesis:** {description}\n"
            f"**Wall time:** {wall_time_min:.1f} min\n"
            f"**Result:** EM={em:.4f} vs prev best={entry.get('prev_best', -1.0):.4f}\n"
            f"**Metric source:** {metrics['source']}\n"
            + ("**Recovery:** checkpoint fallback used because final results were missing.\n" if metrics["is_partial"] else "")
            + (f"**Run error:** {entry['run_error']}\n" if entry.get("run_error") else "")
        )
        _append_experiment_summary(entry)
        em_threshold = exp_cfg.get("em_threshold", 0.5)
        if em >= em_threshold and entry["n_level"] == memory["n_level"]:
            next_n = entry["n_level"] * 2
            memory["n_level"] = next_n
            memory["current_best"] = {"variant": "none", "em": -1.0, "n_level": next_n}
            append_research_log(
                f"## >>> N-level advanced to N={memory['n_level']} <<<\n"
                f"Previous N achieved EM={em:.4f} >= threshold {exp_cfg['em_threshold']}.\n"
            )
        recovered += 1

    if recovered or unresolved:
        update_program_md(memory["n_level"], memory["current_best"]["em"], memory["current_best"]["variant"])

    return recovered, unresolved


def _recover_metrics_for_entry(entry: dict) -> bool:
    exp_path = entry.get("exp_path")
    if not exp_path or entry.get("em_score") is not None:
        return False

    try:
        metrics = get_metrics(exp_path)
    except Exception:
        return False

    entry["em_score"] = metrics["exact_match"]
    entry["token_accuracy"] = metrics["token_accuracy"]
    entry["metric_step"] = metrics["step"]
    entry["metric_source"] = metrics["source"]
    entry["is_partial"] = metrics["is_partial"]
    entry["recovery_status"] = "recovered"
    entry["needs_retry"] = False
    entry["status"] = "completed"
    if entry.get("verdict") == "failed":
        entry["verdict"] = "recovered"

    append_research_log(
        f"## Iter {entry.get('id', '?')} — RECOVERED — N={entry.get('n_level', '?')}\n"
        f"**Recovered from:** {metrics['source']}\n"
        f"**Recovered EM:** {metrics['exact_match']:.4f}\n"
    )
    _append_experiment_summary(entry)
    return True


def _reconcile_recoverable_runs(memory: dict) -> int:
    recovered = 0
    for entry in memory["experiments"]:
        if _recover_metrics_for_entry(entry):
            recovered += 1
    return recovered


def _get_retry_candidate(memory: dict, n_level: int) -> dict | None:
    if not memory["experiments"]:
        return None

    last = memory["experiments"][-1]
    if last.get("n_level") != n_level:
        return None
    if not last.get("needs_retry"):
        return None
    if not last.get("exp_path"):
        return None
    return last


def git_revert_model() -> None:
    result = subprocess.run(
        ["git", "checkout", "--", str(STREAM_MODEL_FILE.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[WARN] git revert model failed: {result.stderr.strip()}")


def git_revert_config() -> None:
    result = subprocess.run(
        ["git", "checkout", "--", str(STREAM_CONFIG_FILE.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[WARN] git revert config failed: {result.stderr.strip()}")


def git_commit(message: str) -> None:
    files = [
        str(STREAM_MODEL_FILE.relative_to(REPO_ROOT)),
        str(STREAM_CONFIG_FILE.relative_to(REPO_ROOT)),
        str(STREAM_PROGRAM_MD.relative_to(REPO_ROOT)),
        str(RESEARCH_LOG.relative_to(REPO_ROOT)),
        str(MEMORY_FILE.relative_to(REPO_ROOT)),
        str(SUMMARY_FILE.relative_to(REPO_ROOT)),
    ]
    if HUMAN_DIRECTIONS_FILE.exists():
        files.append(str(HUMAN_DIRECTIONS_FILE.relative_to(REPO_ROOT)))
    if EXPERIMENT_QUEUE_FILE.exists():
        files.append(str(EXPERIMENT_QUEUE_FILE.relative_to(REPO_ROOT)))

    add_result = subprocess.run(["git", "add"] + files, cwd=REPO_ROOT, capture_output=True, text=True)
    if add_result.returncode != 0:
        raise RuntimeError(f"git add failed: {add_result.stderr.strip() or add_result.stdout.strip()}")

    commit_result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if commit_result.returncode != 0:
        detail = commit_result.stderr.strip() or commit_result.stdout.strip()
        raise RuntimeError(f"git commit failed: {detail}")


EXPERIMENT_TIMEOUT_SEC = 2 * 60 * 60  # 2 hours


def _get_single_value(param_value):
    """Extract single value from config param (handles both scalar and {values, default} format)."""
    if isinstance(param_value, dict):
        if "values" in param_value:
            return param_value.get("default", param_value.get("values")[0])
        return param_value.get("default", param_value)
    return param_value


def _detect_broken_base(memory: dict, k: int = 3) -> str | None:
    """Return the common run_error if the last k completed/failed iters all failed with the same error.

    This detects the case where the committed HEAD itself is broken: every iteration
    starts from the same bad base, fails identically, reverts to HEAD, and loops forever.
    """
    recent = [
        e for e in memory["experiments"]
        if e.get("stream_id", STREAM_ID) == STREAM_ID
        and e.get("status") in ("completed", "failed", "unresolved")
    ][-k:]
    if len(recent) < k:
        return None
    errors = [e.get("run_error") or "" for e in recent]
    if all(errors) and len(set(errors)) == 1:
        return errors[0]
    return None


def run_experiment(exp_path_rel: str, n_pairs: int, exp_cfg: dict) -> None:
    """Run single experiment. For sweeps, use _run_sweep() instead."""
    env = os.environ.copy()
    
    learning_rate = exp_cfg.get("learning_rate")
    if learning_rate is None:
        raise KeyError(
            "learning_rate not found in config. Available keys: {list(exp_cfg.keys())}"
        )
    learning_rate = _get_single_value(learning_rate)

    # Pass main script from config so the shell wrapper stays agnostic
    _cfg = yaml.safe_load(CONFIG_FILE.read_text())
    env["MAIN_SCRIPT"] = _cfg.get("main_script", "run_rmm_on_kv_retrieval-v2.py")

    # Standard short-name mappings used by the shell script
    env.update({
        "L": str(_get_single_value(exp_cfg["n_layer"])),
        "H": str(_get_single_value(exp_cfg["n_head"])),
        "D": str(_get_single_value(exp_cfg["n_embd"])),
        "K": str(_get_single_value(exp_cfg["n_keys"])),
        "V": str(_get_single_value(exp_cfg["n_values"])),
        "PAIRS_PER_SEGMENT": str(_get_single_value(exp_cfg["pairs_per_segment"])),
        "LR": str(learning_rate),
        "PER_DEVICE_BATCH_SIZE": str(_get_single_value(exp_cfg["batch_size"])),
        "EVAL_STEPS": str(_get_single_value(exp_cfg["eval_steps"])),
        "LOGGING_STEPS": str(_get_single_value(exp_cfg["logging_steps"])),
        "WARMUP_STEPS": str(_get_single_value(exp_cfg["warmup_steps"])),
        "EARLY_STOPPING_PATIENCE": str(_get_single_value(exp_cfg["early_stopping_patience"])),
        "BASE_MODEL": str(_get_single_value(exp_cfg["base_model"])),
    })

    # Pass all remaining exp_cfg keys as uppercase env vars so model-specific
    # parameters (state_size, expand_v, fla_layer, n_mem_tokens, …) reach the
    # shell script without any changes here.
    _skip = {"n_layer", "n_head", "n_embd", "n_keys", "n_values", "pairs_per_segment",
             "learning_rate", "batch_size", "eval_steps", "logging_steps",
             "warmup_steps", "early_stopping_patience", "base_model",
             "max_steps", "em_threshold", "output_path"}
    for key, val in exp_cfg.items():
        if key not in _skip:
            env[key.upper()] = str(_get_single_value(val))

    max_steps = _get_single_value(exp_cfg.get("max_steps", 25000))
    
    # Use stream-specific runs directory
    stream_exp_path = str(STREAM_RUNS_DIR / exp_path_rel)
    cmd = ["bash", str(RUN_SCRIPT), stream_exp_path, str(n_pairs), str(max_steps)]
    print(f"[run] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env, timeout=EXPERIMENT_TIMEOUT_SEC)
    if result.returncode != 0:
        raise RuntimeError(f"Experiment script exited with code {result.returncode}")


def _run_sweep(exp_path_rel: str, n_pairs: int, exp_cfg: dict, sweep_param: str, sweep_values: list, subfolder_prefix: str) -> float:
    """Run sweep over multiple values of one parameter. Returns best EM from eval_harness."""
    from eval_harness import get_em
    
    best_em = -1.0
    for i, value in enumerate(sweep_values):
        subfolder_rel = f"{exp_path_rel}_{subfolder_prefix}_{i}"
        subfolder_full = str(STREAM_RUNS_DIR / subfolder_rel)
        cfg_copy = exp_cfg.copy()
        cfg_copy[sweep_param] = value
        
        print(f"[sweep] {sweep_param}={value} ({i+1}/{len(sweep_values)})")
        try:
            run_experiment(subfolder_rel, n_pairs, cfg_copy)
            em = get_em(subfolder_full)
            print(f"[sweep] {sweep_param}={value} -> EM={em:.4f}")
            best_em = max(best_em, em)
        except Exception as e:
            print(f"[sweep] {sweep_param}={value} -> FAILED: {e}")
    
    return best_em


def sanity_check(code: str) -> None:
    """Quick import-level sanity check by writing to a temp file and importing it."""
    import ast
    import tempfile
    import importlib.util

    # 1. syntax
    ast.parse(code)  # raises SyntaxError if broken

    # 2. import check — write to stream-specific modeling_rmt directory
    stream_modeling_dir = STREAM_DIR / "modeling_rmt"
    stream_modeling_dir.mkdir(parents=True, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=stream_modeling_dir, delete=False, mode="w"
    ) as f:
        tmp_path = f.name
        f.write(code)
    try:
        spec = importlib.util.spec_from_file_location("_sanity_check_module", tmp_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.unlink(tmp_path)


# ── stream initialization ─────────────────────────────────────────────────────

def _find_next_stream_id() -> str:
    """Auto-discover next available stream ID."""
    runs_autoresearch = REPO_ROOT / "runs" / "autoresearch"
    if not runs_autoresearch.exists():
        return "0"
    
    existing = []
    for item in runs_autoresearch.iterdir():
        if item.is_dir() and item.name.startswith("stream_"):
            try:
                sid = int(item.name.split("_")[1])
                existing.append(sid)
            except (IndexError, ValueError):
                continue
    
    return str(max(existing) + 1) if existing else "0"

def _init_stream(stream_id: str | None = None, model_file_rel: str = "modeling_rmt/huggingface_rmm_v2.py") -> str:
    """Initialize stream directory structure and return stream ID."""
    global STREAM_DIR, STREAM_MODEL_FILE, STREAM_CONFIG_FILE, STREAM_PROGRAM_MD
    global STREAM_ARTIFACTS_DIR, STREAM_RUNS_DIR, STREAM_ID
    
    # Auto-detect next stream ID if none provided
    if stream_id is None:
        stream_id = _find_next_stream_id()
        os.environ["AUTORESEARCH_STREAM_ID"] = stream_id
    
    STREAM_ID = stream_id
    STREAM_DIR = REPO_ROOT / "runs" / "autoresearch" / f"stream_{STREAM_ID}"
    STREAM_RUNS_DIR = STREAM_DIR  # Experiment runs go directly in stream folder
    _model_rel = Path(model_file_rel)
    STREAM_MODEL_FILE = STREAM_DIR / _model_rel.parent / _model_rel.name
    STREAM_CONFIG_FILE = STREAM_DIR / "experiment_config.yaml"
    STREAM_PROGRAM_MD = STREAM_DIR / "program.md"
    STREAM_ARTIFACTS_DIR = STREAM_DIR / "artifacts"
    
    # Create directory structure
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    STREAM_MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    STREAM_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    STREAM_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Copy initial files if they don't exist
    if not STREAM_MODEL_FILE.exists():
        import shutil
        shutil.copy2(SHARED_MODEL_FILE, STREAM_MODEL_FILE)
        print(f"[stream {STREAM_ID}] copied model file to {STREAM_MODEL_FILE}")
    
    if not STREAM_CONFIG_FILE.exists():
        import shutil
        shutil.copy2(SHARED_EXPERIMENT_CONFIG_FILE, STREAM_CONFIG_FILE)
        print(f"[stream {STREAM_ID}] copied config file to {STREAM_CONFIG_FILE}")
    
    print(f"[stream {STREAM_ID}] initialized at {STREAM_DIR}")
    return STREAM_ID


# ── file locking helpers ──────────────────────────────────────────────────────

def _read_memory_locked() -> dict:
    """Read memory file with shared lock."""
    with open(MEMORY_FILE, 'r') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def _write_memory_locked(memory: dict) -> None:
    """Write memory file with exclusive lock."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = MEMORY_FILE.with_suffix('.tmp')
    with open(tmp_file, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(memory, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            tmp_file.rename(MEMORY_FILE)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def _append_research_log_locked(entry: str) -> None:
    """Append to research log with exclusive lock."""
    RESEARCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RESEARCH_LOG, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(entry + "\n\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ── experiment queue ──────────────────────────────────────────────────────────

def load_experiment_queue() -> dict:
    if not EXPERIMENT_QUEUE_FILE.exists():
        return {"queue": [], "last_directions_hash": None, "last_updated": None}
    with open(EXPERIMENT_QUEUE_FILE, "r") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_experiment_queue(queue_data: dict) -> None:
    EXPERIMENT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    queue_data["last_updated"] = datetime.now().isoformat()
    tmp_file = EXPERIMENT_QUEUE_FILE.with_suffix(".queue_tmp")
    with open(tmp_file, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(queue_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    tmp_file.rename(EXPERIMENT_QUEUE_FILE)


def _directions_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _maybe_enqueue_human_directions(planner_cfg: dict, memory: dict) -> None:
    """Parse human_directions.md and enqueue new plans if content has changed."""
    if not HUMAN_DIRECTIONS_FILE.exists():
        return
    directions_text = HUMAN_DIRECTIONS_FILE.read_text().strip()
    if not directions_text:
        return

    current_hash = _directions_hash(directions_text)
    queue_data = load_experiment_queue()

    if queue_data.get("last_directions_hash") == current_hash:
        return  # unchanged since last parse

    print("[queue] human_directions.md changed — extracting experiment plans...")
    recent = [e for e in memory["experiments"] if e.get("status") != "running"][-10:]

    try:
        new_plans = parse_human_directions(directions_text, recent, planner_cfg)
    except Exception as exc:
        print(f"[queue] WARNING: could not parse human directions: {exc}")
        queue_data["last_directions_hash"] = current_hash
        save_experiment_queue(queue_data)
        return

    existing_hyps = {item.get("hypothesis", "").lower().strip() for item in queue_data["queue"]}
    added = 0
    for plan_item in new_plans:
        hyp_text = plan_item.get("hypothesis", "").lower().strip()
        if hyp_text and hyp_text not in existing_hyps:
            plan_item["source"] = "human_directions"
            plan_item["created_at"] = datetime.now().isoformat()
            queue_data["queue"].append(plan_item)
            existing_hyps.add(hyp_text)
            added += 1

    queue_data["last_directions_hash"] = current_hash
    save_experiment_queue(queue_data)
    print(f"[queue] added {added} plan(s) (queue size: {len(queue_data['queue'])})")


# ── main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    # Ctrl+C → immediate exit, no cleanup needed
    signal.signal(signal.SIGINT, lambda *_: (print("\n[interrupted] exiting."), sys.exit(0)))

    # Load config first so we can pass model_file_rel to _init_stream
    cfg = load_config()
    global SHARED_MODEL_FILE
    SHARED_MODEL_FILE = REPO_ROOT / cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py")

    # Initialize stream
    _init_stream(_STREAM_ID_ARG, model_file_rel=cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py"))

    _ensure_cursor_bridge(cfg)
    exp_cfg = load_experiment_config()
    planner_cfg = cfg["llm"]["planner"]
    executor_cfg = cfg["llm"]["executor"]
    auto_commit = cfg.get("git", {}).get("auto_commit", True)
    n_start = cfg.get("n_start", 2)

    memory = load_memory()

    # Initialise n_level from memory or config
    if memory["n_level"] is None:
        memory["n_level"] = n_start

    n_level = memory["n_level"]
    current_best_em = memory["current_best"]["em"]
    best_variant = memory["current_best"]["variant"]

    runs_dir = STREAM_RUNS_DIR

    _ensure_runtime_files()
    if not STREAM_PROGRAM_MD.exists():
        update_program_md(n_level, current_best_em, best_variant)

    max_iters = cfg.get("max_iters", 100)
    iter_start = len(memory["experiments"])

    for iter_id in range(iter_start, iter_start + max_iters):
        # Outer safety net: catch any unhandled exception so the loop continues
        try:
            _run_iter(
                iter_id=iter_id,
                cfg=cfg,
                exp_cfg=exp_cfg,
                planner_cfg=planner_cfg,
                executor_cfg=executor_cfg,
                memory=memory,
                n_level=n_level,
                current_best_em=current_best_em,
                best_variant=best_variant,
                runs_dir=runs_dir,
                auto_commit=auto_commit,
            )
        except SystemExit:
            raise  # let SIGINT exit propagate
        except Exception as exc:
            print(f"[FATAL] unhandled exception in iter {iter_id}: {exc}")
            _record_failed_iter(
                memory,
                iter_id,
                n_level,
                current_best_em,
                f"unhandled: {exc}",
                planner_trace=None,
                executor_trace=None,
            )
            save_memory(memory)
            continue

        # Read back updated state from memory after the iteration
        n_level = memory["n_level"]
        current_best_em = memory["current_best"]["em"]
        best_variant = memory["current_best"]["variant"]

    print("\n[done] autoresearch loop completed.")
    print(f"Best EM achieved: {current_best_em:.4f} at N={n_level}")


N_EXECUTOR_RETRIES = 4


def _execute_with_retries(hypothesis, current_content, executor_cfg, is_yaml=False):
    """Run executor with validation retries. Returns (new_content, trace) or raises RuntimeError."""
    last_error = None
    last_trace = None
    label = "config" if is_yaml else "code"

    for attempt in range(1, N_EXECUTOR_RETRIES + 1):
        print(f"[executor] applying {label} change (attempt {attempt}/{N_EXECUTOR_RETRIES})...")
        try:
            result = execute_with_trace_full(hypothesis, current_content, executor_cfg, error_context=last_error, is_yaml=is_yaml)
            new_content, trace = result if isinstance(result, tuple) else (result, {})
        except Exception as e:
            last_error = f"Executor error: {e}"
            print(f"[executor] ERROR: {e}")
            continue

        if not is_yaml and new_content.strip() == current_content.strip():
            print("[WARN] executor returned unchanged code — retrying")
            continue

        check_label = "validate" if is_yaml else "sanity"
        print(f"[{check_label}] checking modified {label}...")
        try:
            if is_yaml:
                _validate_yaml(new_content)
            else:
                sanity_check(new_content)
            print(f"[{check_label}] OK")
            return new_content, trace
        except Exception as e:
            last_error = f"{'YAML validation' if is_yaml else 'Sanity check'} failed: {e}"
            last_trace = trace
            print(f"[{check_label}] FAILED (attempt {attempt}): {e}")

    raise RuntimeError(f"executor failed after {N_EXECUTOR_RETRIES} attempts: {last_error}")


def _run_iter(
    iter_id: int,
    cfg: dict,
    exp_cfg: dict,
    planner_cfg: dict,
    executor_cfg: dict,
    memory: dict,
    n_level: int,
    current_best_em: float,
    best_variant: str,
    runs_dir: Path,
    auto_commit: bool,
) -> None:
    is_baseline = (iter_id == 0)
    hypothesis = None
    retry_of = None
    retry_candidate = None
    change_applied = False
    config_changed = False
    prev_best_em = current_best_em  # capture before any mutation
    iter_tag = f"iter_{iter_id:03d}{'_baseline' if is_baseline else ''}"
    planner_trace = None
    executor_trace = None

    if is_baseline:
        print(f"[stream {STREAM_ID}] [iter 0] Running baseline (no changes to model file)")
        description = f"[Stream {STREAM_ID}] baseline — exact copy of v2"
    else:
        recovered_pending, unresolved_pending = _reconcile_running_entries(memory, exp_cfg)
        if recovered_pending or unresolved_pending:
            print(
                f"[recovery] resolved {recovered_pending} running run(s), "
                f"marked {unresolved_pending} for retry"
            )
            save_memory(memory)
            n_level = memory["n_level"]
            current_best_em = memory["current_best"]["em"]
            best_variant = memory["current_best"]["variant"]

        recovered_count = _reconcile_recoverable_runs(memory)
        if recovered_count:
            print(f"[recovery] backfilled {recovered_count} prior run(s) from checkpoints")
            save_memory(memory)
            n_level = memory["n_level"]
            current_best_em = memory["current_best"]["em"]
            best_variant = memory["current_best"]["variant"]

        retry_candidate = _get_retry_candidate(memory, n_level)
        if retry_candidate:
            retry_of = retry_candidate["id"]
            iter_tag = _build_retry_tag(memory, retry_of)
            hypothesis = retry_candidate.get("hypothesis")
            description = retry_candidate.get("description", f"retry of iter {retry_of}")
            print(f"[retry] re-running unresolved iter {retry_of} as {iter_tag}")

        # ── Queue / Planner ──
        planner_trace = None
        if retry_candidate is None:
            # Check if the committed HEAD itself is broken (same error repeated k times)
            broken_error = _detect_broken_base(memory)
            if broken_error:
                print(f"[broken-base] same error repeated 3x — synthesizing fix-base hypothesis")
                hypothesis = {
                    "hypothesis": f"Fix broken base: {broken_error[:120]}",
                    "target_component": str(STREAM_MODEL_FILE.relative_to(REPO_ROOT)),
                    "rationale": (
                        "The committed HEAD crashes at runtime with the same error on every "
                        "iteration. Fix the root cause before any other change."
                    ),
                    "instruction": (
                        f"The model file at HEAD crashes at runtime with this error:\n{broken_error}\n"
                        "Find and fix the root cause. Do NOT introduce new features."
                    ),
                    "run_name": "fix_broken_base",
                    "_fix_base": True,
                }
                description = hypothesis["hypothesis"]
            else:
                _maybe_enqueue_human_directions(planner_cfg, memory)
                queue_data = load_experiment_queue()

                if queue_data["queue"]:
                    hypothesis = queue_data["queue"].pop(0)
                    for meta_key in ("source", "created_at"):
                        hypothesis.pop(meta_key, None)
                    save_experiment_queue(queue_data)
                    description = hypothesis.get("hypothesis", f"iter {iter_id}")
                    print(f"[queue] dequeued: {description} (remaining: {len(queue_data['queue'])})")
                else:
                    print("[planner] queue empty — generating hypothesis...")
                    program_md = load_program_md()
                    recent = [entry for entry in memory["experiments"] if entry.get("status") != "running"][-10:]

                    N_PLANNER_RETRIES = 2
                    planner_error = None
                    for attempt in range(1, N_PLANNER_RETRIES + 1):
                        try:
                            hypothesis, planner_trace = plan_with_trace_full(program_md, recent, planner_cfg, error_context=planner_error, iter_tag=iter_tag)
                            break
                        except Exception as e:
                            planner_error = str(e)
                            print(f"[planner] ERROR (attempt {attempt}/{N_PLANNER_RETRIES}): {e}")
                    else:
                        _record_failed_iter(memory, iter_id, n_level, current_best_em, f"planner failed after {N_PLANNER_RETRIES} attempts: {planner_error}", planner_trace=planner_trace)
                        save_memory(memory)
                        return

                    print(f"[planner] hypothesis: {hypothesis.get('hypothesis', '')}")
                    description = hypothesis.get("hypothesis", f"iter {iter_id}")

        executor_trace = None
        if hypothesis is not None:
            target = hypothesis.get("target_component", "")
            is_config_change = _is_config_change_target(target)
            target_file = STREAM_CONFIG_FILE if is_config_change else STREAM_MODEL_FILE
            current_content = target_file.read_text()

            try:
                new_content, executor_trace = _execute_with_retries(
                    hypothesis, current_content, executor_cfg, is_yaml=is_config_change,
                )
            except RuntimeError as e:
                _record_failed_iter(memory, iter_id, n_level, current_best_em, str(e), hypothesis, planner_trace=planner_trace, executor_trace=executor_trace)
                save_memory(memory)
                return

            target_file.write_text(new_content)
            change_applied = True
            config_changed = is_config_change
            if is_config_change:
                exp_cfg = yaml.safe_load(new_content)
                print("[config] updated experiment config")

    run_name = hypothesis.get("run_name", "") if hypothesis else ""
    if run_name:
        run_name = run_name.lower().replace(" ", "_").replace("-", "_")
        exp_path_rel = f"n{n_level}/{iter_tag}_{run_name}"
    else:
        exp_path_rel = f"n{n_level}/{iter_tag}"
    
    # Full path for metrics lookup
    exp_path_full = str(STREAM_RUNS_DIR / exp_path_rel)

    print(f"\n{'='*60}")
    print(f"  Iteration {iter_id}  |  N={n_level}  |  best_EM={current_best_em:.4f}")
    print(f"  exp_path: {exp_path_full}")
    print(f"{'='*60}")

    running_entry = _record_running_iter(
        memory=memory,
        iter_id=iter_id,
        iter_tag=iter_tag,
        n_level=n_level,
        current_best_em=current_best_em,
        description=description,
        exp_path=exp_path_full,
        hypothesis=hypothesis,
        retry_of=retry_of,
    )
    save_memory(memory)

    # ── Run experiment ──
    t0 = time.time()
    run_error = None
    best_em_for_sweep = None
    try:
        # Check for sweep parameters (one sweep per run)
        # Only run a sweep if the hypothesis explicitly opts in; otherwise flatten to defaults
        sweep_param = None
        sweep_values = None
        sweep_prefix = None
        if hypothesis and hypothesis.get("use_sweep"):
            for param, val in exp_cfg.items():
                if isinstance(val, dict) and "values" in val:
                    sweep_param = param
                    sweep_values = val["values"]
                    sweep_prefix = param.replace("_", "")[:8]
                    break
        else:
            # Flatten any lingering sweep-format values to their defaults
            exp_cfg = {k: _get_single_value(v) for k, v in exp_cfg.items()}
        
        if sweep_param and sweep_values:
            print(f"[sweep] Running sweep on {sweep_param}: {sweep_values}")
            best_em_for_sweep = _run_sweep(
                exp_path_rel, n_level, exp_cfg, sweep_param, sweep_values, sweep_prefix
            )
        else:
            run_experiment(exp_path_rel, n_pairs=n_level, exp_cfg=exp_cfg)
    except KeyError as e:
        error_msg = f"Configuration error: missing required key {e}. Current exp_cfg keys: {list(exp_cfg.keys())}"
        print(f"[experiment] ERROR: {error_msg}")
        run_error = error_msg
    except Exception as e:
        print(f"[experiment] ERROR: {e}")
        run_error = f"experiment error: {e}"

    wall_min = (time.time() - t0) / 60

    # ── Evaluate ──
    try:
        if best_em_for_sweep is not None:
            metrics = {
                "exact_match": best_em_for_sweep,
                "token_accuracy": best_em_for_sweep,
                "step": 0,
                "source": "sweep",
                "is_partial": False,
            }
        else:
            metrics = get_metrics(exp_path_full)
        em = metrics["exact_match"]
    except Exception as e:
        print(f"[eval] ERROR reading metrics: {e}")
        if change_applied:
            _revert_entry_change(running_entry)
        _mark_entry_unresolved(running_entry, run_error or f"eval error: {e}",
                               planner_trace=planner_trace, executor_trace=executor_trace)
        save_memory(memory)
        return

    if run_error:
        print(f"[recovery] recovered metrics from {metrics['source']} after run failure")

    print(f"[eval] EM={em:.4f}  (prev best={prev_best_em:.4f})")

    # ── Keep or revert ──
    prior_best = memory["current_best"]["em"]
    verdict, em = _finalize_running_entry(memory, exp_cfg, running_entry, metrics, wall_min, run_error)
    current_best_em = memory["current_best"]["em"]
    best_variant = memory["current_best"]["variant"]
    if memory["current_best"]["em"] > prior_best:
        print(f"[result] KEPT  — new best EM={em:.4f}")

        # Mark human_directions item as [Done] if this was implementing one
        if hypothesis and hypothesis.get("human_directions_item"):
            update_human_directions_completed(hypothesis["human_directions_item"])
    elif change_applied:
        print(f"[result] REVERTED — EM={em:.4f} did not beat {prior_best:.4f}")

    # ── Update program.md ──
    update_program_md(n_level, current_best_em, best_variant)

    # ── Append to research log ──
    log_entry = (
        f"## Iter {iter_id} — {verdict} — EM: {em:.4f} (N={n_level})\n"
        f"**Hypothesis:** {description}\n"
        f"**Wall time:** {wall_min:.1f} min\n"
        f"**Result:** EM={em:.4f} vs prev best={prev_best_em:.4f}\n"
        f"**Metric source:** {metrics['source']}\n"
    )
    if metrics["is_partial"]:
        log_entry += "**Recovery:** checkpoint fallback used because final results were missing.\n"
    if run_error:
        log_entry += f"**Run error:** {run_error}\n"
    if hypothesis and hypothesis.get("rationale"):
        log_entry += f"**Rationale:** {hypothesis['rationale']}\n"
    append_research_log(log_entry)

    # ── Advance N-level if threshold reached ──
    em_threshold = exp_cfg.get("em_threshold")
    if em_threshold is None:
        raise KeyError(
            f"em_threshold not found in config. Available keys: {list(exp_cfg.keys())}"
        )
    
    if em >= em_threshold:
        next_n = n_level * 2
        print(f"[advance] EM={em:.4f} >= {em_threshold} — advancing N: {n_level} → {next_n}")
        n_level = next_n
        memory["n_level"] = n_level
        current_best_em = -1.0
        memory["current_best"] = {"variant": "none", "em": -1.0, "n_level": n_level}
        update_program_md(n_level, current_best_em, best_variant)
        append_research_log(
            f"## >>> N-level advanced to N={n_level} <<<\n"
            f"Previous N achieved EM={em:.4f} >= threshold {em_threshold}.\n"
        )

    save_memory(memory)

    # ── Save traces to artifacts ──
    _save_traces_to_artifacts(iter_tag, planner_trace, executor_trace)

    # ── Git commit (non-fatal) ──
    if auto_commit:
        try:
            change_type = "config" if config_changed else "model"
            commit_msg = (
                f"autoresearch stream {STREAM_ID} iter {iter_id}: {verdict} | EM={em:.4f} | N={n_level} | {change_type}\n\n"
                f"{description}"
            )
            git_commit(commit_msg)
        except Exception as e:
            print(f"[WARN] git commit failed (non-fatal): {e}")


def _record_failed_iter(
    memory: dict,
    iter_id: int,
    n_level: int,
    current_best_em: float,
    error_msg: str,
    hypothesis: dict | None = None,
    exp_path: str | None = None,
    wall_time_min: float = 0,
    recovery_status: str = "not_attempted",
    needs_retry: bool = False,
    retry_of: int | None = None,
    run_error: str | None = None,
    planner_trace: dict | None = None,
    executor_trace: dict | None = None,
) -> None:
    iter_tag = f"iter_{iter_id:03d}"
    entry = _create_iter_entry(
        memory=memory,
        iter_id=iter_id,
        iter_tag=iter_tag,
        n_level=n_level,
        current_best_em=current_best_em,
        description=f"FAILED: {error_msg}",
        exp_path=exp_path or "",
        hypothesis=hypothesis,
        retry_of=retry_of,
        status="failed",
    )
    entry.update({
        "wall_time_min": round(wall_time_min, 1),
        "metric_source": None,
        "is_partial": False,
        "recovery_status": recovery_status,
        "needs_retry": needs_retry,
        "run_error": run_error or error_msg,
    })
    append_research_log(
        f"## Iter {iter_id} — FAILED — N={n_level}\n"
        f"**Error:** {error_msg}\n"
        + (f"**exp_path:** {exp_path}\n" if exp_path else "")
        + (f"**Recovery status:** {recovery_status}\n" if recovery_status else "")
        + ("**Next action:** retry this experiment before planning a new one.\n" if needs_retry else "")
    )
    _append_experiment_summary(entry, error_msg)
    _save_traces_to_artifacts(iter_tag, planner_trace, executor_trace)


if __name__ == "__main__":
    main()
