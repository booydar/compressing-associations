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
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import yaml

# resolve repo root (parent of .autoresearch/)
REPO_ROOT = Path(__file__).resolve().parent.parent
AUTORESEARCH_DIR = REPO_ROOT / ".autoresearch"

sys.path.insert(0, str(AUTORESEARCH_DIR))

from eval_harness import get_em
from planner import plan
from executor import execute

MODEL_FILE = REPO_ROOT / "modeling_rmt" / "huggingface_rmca_v3.py"
PROGRAM_MD = AUTORESEARCH_DIR / "program.md"
RESEARCH_LOG = AUTORESEARCH_DIR / "research_log.md"
MEMORY_FILE = AUTORESEARCH_DIR / "results_memory.json"
CONFIG_FILE = AUTORESEARCH_DIR / "config.yaml"
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_autoresearch_exp.sh"


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


def _load_dotenv(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return {
        "current_best": {"variant": "none", "em": -1.0, "n_level": 0},
        "n_level": None,
        "experiments": [],
    }


def save_memory(memory: dict) -> None:
    # Keep at most 50 experiments to avoid unbounded growth
    if len(memory["experiments"]) > 50:
        memory["experiments"] = memory["experiments"][-50:]
    MEMORY_FILE.write_text(json.dumps(memory, indent=2))


def load_program_md() -> str:
    return PROGRAM_MD.read_text() if PROGRAM_MD.exists() else ""


def update_program_md(n_level: int, current_best_em: float, best_variant: str, understanding: str = "") -> None:
    content = f"""# Research Program

## Objective
Maximize exact-match (EM) on associative retrieval task using RMCA.
Advance N-level: N=2 → N=4 → N=8 as EM ≥ 0.99 at each level.

## Constraints
- Model file: modeling_rmt/huggingface_rmca_v3.py
- No parameter count explosion (justify any increase)
- Max experiment length: {load_config()['experiment']['max_steps']} steps

## Current State
- N-level: {n_level}
- Current best EM: {current_best_em:.4f}
- Best variant: {best_variant}
- Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Current Understanding
{understanding if understanding else '(updated each iteration by autoresearch loop)'}
"""
    PROGRAM_MD.write_text(content)


def append_research_log(entry: str) -> None:
    with open(RESEARCH_LOG, "a") as f:
        f.write(entry + "\n\n")


def git_revert_model() -> None:
    result = subprocess.run(
        ["git", "checkout", "--", str(MODEL_FILE.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[WARN] git revert failed: {result.stderr.strip()}")


def git_commit(message: str) -> None:
    files = [
        str(MODEL_FILE.relative_to(REPO_ROOT)),
        str(PROGRAM_MD.relative_to(REPO_ROOT)),
        str(RESEARCH_LOG.relative_to(REPO_ROOT)),
        str(MEMORY_FILE.relative_to(REPO_ROOT)),
    ]
    subprocess.run(["git", "add"] + files, cwd=REPO_ROOT, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, capture_output=True)


def run_experiment(exp_path: str, n_pairs: int, cfg: dict) -> None:
    exp_cfg = cfg["experiment"]
    env = os.environ.copy()
    env.update({
        "L": str(exp_cfg["n_layer"]),
        "H": str(exp_cfg["n_head"]),
        "D": str(exp_cfg["n_embd"]),
        "K": str(exp_cfg["n_keys"]),
        "V": str(exp_cfg["n_values"]),
        "N_MEM_TOKENS": str(exp_cfg["n_mem_tokens"]),
        "PAIRS_PER_SEGMENT": str(exp_cfg["pairs_per_segment"]),
        "LR": str(exp_cfg["lr"]),
        "PER_DEVICE_BATCH_SIZE": str(exp_cfg["batch_size"]),
        "EVAL_STEPS": str(exp_cfg["eval_steps"]),
        "LOGGING_STEPS": str(exp_cfg["logging_steps"]),
        "WARMUP_STEPS": str(exp_cfg["warmup_steps"]),
        "EARLY_STOPPING_PATIENCE": str(exp_cfg["early_stopping_patience"]),
        "BASE_MODEL": str(exp_cfg["base_model"]),
    })
    cmd = ["bash", str(RUN_SCRIPT), exp_path, str(n_pairs), str(exp_cfg["max_steps"])]
    print(f"[run] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Experiment script exited with code {result.returncode}")


def sanity_check(code: str) -> None:
    """Quick import-level sanity check by writing to a temp file and importing it."""
    import ast
    import tempfile
    import importlib.util

    # 1. syntax
    ast.parse(code)  # raises SyntaxError if broken

    # 2. import check — write to a temp file and attempt to load the module spec
    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=REPO_ROOT / "modeling_rmt", delete=False, mode="w"
    ) as f:
        tmp_path = f.name
        f.write(code)
    try:
        spec = importlib.util.spec_from_file_location("_sanity_check_module", tmp_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Verify the expected public API is still present
        for name in ("RMCABase", "RMCAConfig", "RMCACell", "MemoryAugmentedLayer"):
            if not hasattr(mod, name):
                raise AttributeError(f"Expected class {name!r} not found after modification")
    finally:
        os.unlink(tmp_path)


# ── main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()
    _ensure_cursor_bridge(cfg)
    exp_cfg = cfg["experiment"]
    planner_cfg = cfg["llm"]["planner"]
    executor_cfg = cfg["llm"]["executor"]
    auto_commit = cfg.get("git", {}).get("auto_commit", True)

    memory = load_memory()

    # Initialise n_level from memory or config
    if memory["n_level"] is None:
        memory["n_level"] = exp_cfg["n_start"]

    n_level = memory["n_level"]
    current_best_em = memory["current_best"]["em"]
    best_variant = memory["current_best"]["variant"]

    runs_dir = REPO_ROOT / "runs-autoresearch"

    if not PROGRAM_MD.exists():
        update_program_md(n_level, current_best_em, best_variant)
    if not RESEARCH_LOG.exists():
        RESEARCH_LOG.write_text(f"# Research Log\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

    max_iters = exp_cfg["max_iters"]
    iter_start = len(memory["experiments"])

    for iter_id in range(iter_start, iter_start + max_iters):
        is_baseline = (iter_id == 0)
        iter_tag = f"iter_{iter_id:03d}{'_baseline' if is_baseline else ''}"
        exp_path = str(runs_dir / f"n{n_level}" / iter_tag)

        print(f"\n{'='*60}")
        print(f"  Iteration {iter_id}  |  N={n_level}  |  best_EM={current_best_em:.4f}")
        print(f"  exp_path: {exp_path}")
        print(f"{'='*60}")

        hypothesis = None
        change_applied = False

        if is_baseline:
            print("[iter 0] Running baseline (no changes to model file)")
            description = "baseline — exact copy of v2"
        else:
            # ── Planner ──
            print("[planner] generating hypothesis...")
            program_md = load_program_md()
            recent = memory["experiments"][-10:]
            try:
                hypothesis = plan(program_md, recent, planner_cfg)
            except Exception as e:
                print(f"[planner] ERROR: {e}")
                _record_failed_iter(memory, iter_id, n_level, current_best_em, f"planner error: {e}")
                save_memory(memory)
                continue

            print(f"[planner] hypothesis: {hypothesis.get('hypothesis', '')}")
            description = hypothesis.get("hypothesis", f"iter {iter_id}")

            # ── Executor ──
            print("[executor] applying change...")
            current_code = MODEL_FILE.read_text()
            try:
                new_code = execute(hypothesis, current_code, executor_cfg)
            except Exception as e:
                print(f"[executor] ERROR: {e}")
                _record_failed_iter(memory, iter_id, n_level, current_best_em, f"executor error: {e}", hypothesis)
                save_memory(memory)
                continue

            # ── Sanity check ──
            print("[sanity] checking modified code...")
            try:
                sanity_check(new_code)
            except Exception as e:
                print(f"[sanity] FAILED: {e}")
                _record_failed_iter(memory, iter_id, n_level, current_best_em, f"sanity check failed: {e}", hypothesis)
                save_memory(memory)
                continue

            MODEL_FILE.write_text(new_code)
            change_applied = True
            print("[sanity] OK")

        # ── Run experiment ──
        t0 = time.time()
        try:
            run_experiment(exp_path, n_pairs=n_level, cfg=cfg)
        except Exception as e:
            print(f"[experiment] ERROR: {e}")
            if change_applied:
                print("[revert] reverting model file...")
                git_revert_model()
            _record_failed_iter(memory, iter_id, n_level, current_best_em, f"experiment error: {e}", hypothesis)
            save_memory(memory)
            continue

        wall_min = (time.time() - t0) / 60

        # ── Evaluate ──
        try:
            em = get_em(exp_path)
        except Exception as e:
            print(f"[eval] ERROR reading metrics: {e}")
            if change_applied:
                git_revert_model()
            _record_failed_iter(memory, iter_id, n_level, current_best_em, f"eval error: {e}", hypothesis)
            save_memory(memory)
            continue

        print(f"[eval] EM={em:.4f}  (prev best={current_best_em:.4f})")

        # ── Keep or revert ──
        if em > current_best_em:
            verdict = "kept"
            current_best_em = em
            best_variant = iter_tag
            memory["current_best"] = {"variant": iter_tag, "em": em, "n_level": n_level}
            print(f"[result] KEPT  — new best EM={em:.4f}")
        else:
            verdict = "reverted" if change_applied else "baseline"
            if change_applied:
                print(f"[result] REVERTED — EM={em:.4f} did not beat {current_best_em:.4f}")
                git_revert_model()

        # ── Record ──
        entry = {
            "id": iter_id,
            "description": description,
            "hypothesis": hypothesis,
            "em_score": em,
            "prev_best": current_best_em if verdict != "kept" else em,
            "verdict": verdict if not is_baseline else "baseline",
            "n_level": n_level,
            "exp_path": exp_path,
            "wall_time_min": round(wall_min, 1),
        }
        memory["experiments"].append(entry)

        # ── Update program.md ──
        update_program_md(n_level, current_best_em, best_variant)

        # ── Append to research log ──
        log_entry = (
            f"## Iter {iter_id} — {verdict} — EM: {em:.4f} (N={n_level})\n"
            f"**Hypothesis:** {description}\n"
            f"**Wall time:** {wall_min:.1f} min\n"
            f"**Result:** EM={em:.4f} vs prev best={current_best_em:.4f if verdict != 'kept' else em:.4f}\n"
        )
        if hypothesis and hypothesis.get("rationale"):
            log_entry += f"**Rationale:** {hypothesis['rationale']}\n"
        append_research_log(log_entry)

        # ── Advance N-level if threshold reached ──
        if em >= exp_cfg["em_threshold"]:
            next_n = n_level * 2
            print(f"[advance] EM={em:.4f} >= {exp_cfg['em_threshold']} — advancing N: {n_level} → {next_n}")
            n_level = next_n
            memory["n_level"] = n_level
            # Reset best EM for new N-level
            current_best_em = -1.0
            memory["current_best"] = {"variant": "none", "em": -1.0, "n_level": n_level}
            update_program_md(n_level, current_best_em, best_variant)
            append_research_log(
                f"## >>> N-level advanced to N={n_level} <<<\n"
                f"Previous N achieved EM={em:.4f} >= threshold {exp_cfg['em_threshold']}.\n"
            )

        save_memory(memory)

        # ── Git commit ──
        if auto_commit:
            commit_msg = (
                f"autoresearch iter {iter_id}: {verdict} | EM={em:.4f} | N={n_level}\n\n"
                f"{description}"
            )
            git_commit(commit_msg)

    print("\n[done] autoresearch loop completed.")
    print(f"Best EM achieved: {current_best_em:.4f} at N={n_level}")


def _record_failed_iter(
    memory: dict,
    iter_id: int,
    n_level: int,
    current_best_em: float,
    error_msg: str,
    hypothesis: dict | None = None,
) -> None:
    memory["experiments"].append({
        "id": iter_id,
        "description": f"FAILED: {error_msg}",
        "hypothesis": hypothesis,
        "em_score": None,
        "prev_best": current_best_em,
        "verdict": "failed",
        "n_level": n_level,
        "exp_path": None,
        "wall_time_min": 0,
    })
    append_research_log(
        f"## Iter {iter_id} — FAILED — N={n_level}\n"
        f"**Error:** {error_msg}\n"
    )


if __name__ == "__main__":
    main()
