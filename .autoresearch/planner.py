"""
Planner agent.

Input  : current model/config context + experiment summary + last N experiment entries
Output : a JSON hypothesis dict:
  {
    "hypothesis": "One-sentence description of the proposed change",
    "target_component": "<model_file> | .autoresearch/experiment_config.yaml",
    "rationale": "Why this change should improve EM on the associative retrieval task",
    "instruction": "Precise instruction for the executor: what to add/change/remove in the model file"
  }
"""
import fcntl
import json
import re
import subprocess
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime
import yaml

sys.path.insert(0, os.path.dirname(__file__))
from llm_client import call_llm, _build_base_url

AUTORESEARCH_DIR = Path(os.path.dirname(__file__))
REPO_ROOT = AUTORESEARCH_DIR.parent
HUMAN_DIRECTIONS_FILE = AUTORESEARCH_DIR / "human_directions.md"
EXPERIMENT_QUEUE_FILE = AUTORESEARCH_DIR / "experiment_queue.json"
SUMMARY_FILE = AUTORESEARCH_DIR / "experiment_summary.md"
CONVENTIONS_FILE = AUTORESEARCH_DIR / "conventions.md"
RESEARCH_LOG = AUTORESEARCH_DIR / "research_log.md"
MEMORY_FILE = AUTORESEARCH_DIR / "results_memory.json"
QUEUE_LOCK_FILE = AUTORESEARCH_DIR / "queue.lock"

# Stream-specific paths (read dynamically via environment)
def get_stream_dir():
    stream_id = os.environ.get("AUTORESEARCH_STREAM_ID", "0")
    return REPO_ROOT / "runs" / "autoresearch" / f"stream_{stream_id}"

def get_model_file():
    cfg_path = AUTORESEARCH_DIR / "config.yaml"
    _cfg = yaml.safe_load(cfg_path.read_text())
    model_rel = Path(_cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py"))
    return get_stream_dir() / model_rel.parent / model_rel.name

def get_config_file():
    return get_stream_dir() / "experiment_config.yaml"

def get_artifacts_dir():
    return get_stream_dir() / "artifacts"

# Dynamic access functions
def get_stream_id():
    return os.environ.get("AUTORESEARCH_STREAM_ID", "0")

# Module-level defaults (will be overridden dynamically via functions)
MODEL_FILE = None
EXPERIMENT_CONFIG_FILE = None
ARTIFACTS_DIR = None


def _artifact_dir(iter_tag: str) -> Path:
    return get_artifacts_dir() / iter_tag
MAX_HUMAN_DIRECTIONS_CHARS = 8000
MAX_CONFIG_CHARS = 8000
MAX_CONVENTIONS_CHARS = 8000
MAX_MODEL_CHARS = 60000
HUMAN_DIRECTION_ITEM_RE = re.compile(
    r"^(?P<number>\d+)\.\s+\[(?P<status>Pending|Running|Done|Failed|Skipped)\]\s+(?P<title>.+)$",
    re.MULTILINE,
)

SYSTEM_PROMPT = """\
You are a research scientist specialising in recurrent neural memory architectures.
Your task is to propose ONE concrete change to improve the model's
exact-match (EM) accuracy on the associative retrieval task.

CURRENT STREAM: {stream_id} (this identifies your research instance)

You may propose changes to:
1. **Architecture** - modifications to {model_file}
2. **Model hyperparameters** - n_layer, n_head, n_embd and model-specific params (in stream-specific experiment_config.yaml)
3. **Training hyperparameters** - learning rate, batch size, warmup steps, etc. (in stream-specific experiment_config.yaml)

CRITICAL: When describing your hypothesis, explicitly state your stream ID context:
- "Stream {stream_id}: Implement gating mechanism in the memory layer"
- "Stream {stream_id}: Explore learning rate sweep from 1e-4 to 1e-2"

CRITICAL RULES:
- HYPERPARAMETER-FIRST POLICY: You are REQUIRED to exhaust hyperparameters tuning before architectural changes.
  Hyperparameters include: n_layer, n_head, n_embd, lr, batch_size, warmup_steps,
  max_steps, weight_decay, and any model-specific params listed in experiment_config.yaml.
- ONLY propose architectural changes if you explicitly list which hyperparameters have been exhausted
  and why further tuning won't help.
- Propose ONLY ONE change per iteration.
- For architectural changes: target {model_file}.
- For hyperparameters changes: target .autoresearch/experiment_config.yaml.
- Do not increase total parameter count by more than ~50% without strong justification.
- Prefer changes that have a clear theoretical motivation.
- Do not repeat a change that has already been tried (see experiment history).
- **SWEEPS**: Only use sweep format if a human direction explicitly requests a parameter
  search. Do NOT use sweep format autonomously.

In your rationale, you MUST explicitly state:
- If proposing hyperparameters: which specific values/ranges you are exploring
- If proposing architecture: which hyperparameters have been exhausted and why further tuning won't help

Respond with ONLY a JSON object, no markdown fences, no extra text:
{{
  "hypothesis": "<one sentence>",
  "target_component": "<{model_file} | .autoresearch/experiment_config.yaml>",
  "rationale": "<2-3 sentences, MUST mention hyperparameters status if proposing architecture>",
  "instruction": "<precise, unambiguous instruction for the code editor>",
  "run_name": "<short, readable name for TB run folder, 2-5 words, lowercase, underscore-separated, e.g., 'adam_optimizer', 'deep_supervision_v2'>"
}}"""


DIRECTOR_SYSTEM_PROMPT = """\
You are a research director for a neural memory architecture project.
Read the free-form human research directions below and extract a list of
concrete, actionable experiment plans. Be conservative: only extract
experiments that are explicitly suggested or clearly implied — do NOT invent ideas.

Each plan must be a JSON object with exactly these fields:
  "hypothesis"       : one-sentence description of the proposed change
  "target_component" : "{model_file}"  OR
                       ".autoresearch/experiment_config.yaml"
  "rationale"        : 1-2 sentences explaining the motivation
  "instruction"      : precise, unambiguous instruction for a code editor
  "run_name"         : 2-5 words, lowercase, underscore-separated (e.g. "lr_sweep_1e3")

RULES:
- Do NOT repeat experiments that already appear in the recent history.
- For hyperparameter changes target .autoresearch/experiment_config.yaml.
- For architecture changes target {model_file}.
- If nothing clearly actionable is found, return an empty array.

Respond with ONLY a JSON array, no markdown fences, no extra text.
"""


class PlannerResponseError(ValueError):
    def __init__(self, message: str, trace: dict):
        super().__init__(message)
        self.trace = trace


def build_planner_context_file(iter_tag: str) -> Path:
    """Create a context file with paths to all important files and save to artifacts."""
    artifact_path = _artifact_dir(iter_tag)
    artifact_path.mkdir(parents=True, exist_ok=True)
    
    context_file = artifact_path / "context.md"
    
    # Build context with file paths and key metadata
    context_lines = [
        "# Planner Context",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Important Files (use these paths to read content)",
        f"- Model: {get_model_file()}",
        f"- Experiment Config: {get_config_file()}",
        f"- Experiment Queue: {EXPERIMENT_QUEUE_FILE}",
        f"- Conventions: {CONVENTIONS_FILE}",
        f"- Research Log: {RESEARCH_LOG}",
        f"- Results Memory: {MEMORY_FILE}",
        f"- Experiment Summary: {SUMMARY_FILE}",
        "",
        "## Key Hyperparameters (from experiment_config.yaml)",
    ]
    
    # Read and include key hyperparameters
    exp_config_file = get_config_file()
    if exp_config_file.exists():
        exp_cfg = yaml.safe_load(exp_config_file.read_text())
        for key in ['n_layer', 'n_head', 'n_embd', 'learning_rate', 'batch_size', 'max_steps']:
            if key in exp_cfg:
                context_lines.append(f"- {key}: {exp_cfg[key]}")
    else:
        context_lines.append("- (config not found)")
    
    context_file.write_text("\n".join(context_lines))
    print(f"[planner] created context file: {context_file}")
    return context_file


def build_planner_messages(
    program_md: str,
    recent_experiments: list[dict],
    error_context: str | None = None,
    iter_tag: str | None = None,
) -> tuple[list[dict], Path | None]:
    del program_md  # intentionally unused to keep planner context bounded

    history_text = _format_history(recent_experiments[-10:])

    # Create context file with paths to important files
    context_file = None
    if iter_tag:
        context_file = build_planner_context_file(iter_tag)

    config_text = _read_text(
        get_config_file(),
        default="(missing experiment_config.yaml)",
        max_chars=MAX_CONFIG_CHARS,
    )
    conventions_text = _read_text(
        CONVENTIONS_FILE,
        default="(missing conventions.md)",
        max_chars=MAX_CONVENTIONS_CHARS,
    )

    # File path references for the planner
    file_refs = f"""## Important Files
- Model code: {get_model_file()}
- Experiment config: {get_config_file()}
- Experiment queue: {EXPERIMENT_QUEUE_FILE}
- Conventions: {CONVENTIONS_FILE}
- Research log: {RESEARCH_LOG}
- Results memory: {MEMORY_FILE}
- Experiment summary: {SUMMARY_FILE}
"""

    user_content = f"""{file_refs}
## Recent Experiment History (last 10, most recent last)
{history_text}

## Current Hyperparameters (.autoresearch/experiment_config.yaml)
{config_text}

## Repository Conventions
{conventions_text}

The experiment queue is empty — propose the next change to try based on the experiment history above."""

    if error_context:
        user_content += (
            "\n\n## Previous Attempt Failed\n"
            "Your previous response failed to parse as JSON or violated the required schema.\n"
            f"Error: {error_context}\n"
            "Please ensure your response is ONLY a valid JSON object."
        )

    # Format system prompt with stream ID and model file from config
    _cfg = yaml.safe_load((AUTORESEARCH_DIR / "config.yaml").read_text())
    _model_file = _cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py")
    formatted_system_prompt = SYSTEM_PROMPT.format(stream_id=get_stream_id(), model_file=_model_file)
    
    return [
        {"role": "system", "content": formatted_system_prompt},
        {"role": "user", "content": user_content},
    ], context_file


def plan_with_trace(
    program_md: str,
    recent_experiments: list[dict],
    provider_cfg: dict,
    error_context: str | None = None,
    iter_tag: str | None = None,
) -> tuple[dict, dict]:
    """
    Call the planner via opencode CLI and return both parsed hypothesis and trace data.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    messages, context_file = build_planner_messages(program_md, recent_experiments, error_context=error_context, iter_tag=iter_tag)
    hypothesis = _call_opencode_planner(messages, provider_cfg, context_file, error_context=error_context, recent_experiments=recent_experiments)
    trace = {
        "messages": messages,
        "hypothesis": hypothesis,
        "context_file": str(context_file) if context_file else None,
        "model_name": provider_cfg.get("model", "unknown"),
        "provider": provider_cfg.get("provider", "unknown"),
    }
    return hypothesis, trace


def plan(program_md: str, recent_experiments: list[dict], provider_cfg: dict, error_context: str | None = None, iter_tag: str | None = None) -> dict:
    result = plan_with_trace(program_md, recent_experiments, provider_cfg, error_context=error_context, iter_tag=iter_tag)
    return result[0] if isinstance(result, tuple) else result


def plan_with_trace_full(program_md: str, recent_experiments: list[dict], provider_cfg: dict, error_context: str | None = None, iter_tag: str | None = None) -> tuple[dict, dict]:
    """
    Call the planner via opencode CLI and return both parsed hypothesis and full trace data for logging.
    Retries once on failure with error context. Saves error trace to artifacts on final failure.
    """
    messages, context_file = build_planner_messages(program_md, recent_experiments, error_context=error_context, iter_tag=iter_tag)
    last_error = error_context
    last_trace = None

    for attempt in range(1, 3):
        try:
            hypothesis = _call_opencode_planner(
                messages, provider_cfg, context_file,
                error_context=last_error,
                recent_experiments=recent_experiments,
            )
            trace = {
                "messages": messages,
                "hypothesis": hypothesis,
                "context_file": str(context_file) if context_file else None,
                "model_name": provider_cfg.get("model", "unknown"),
                "provider": provider_cfg.get("provider", "unknown"),
                "attempt": attempt,
            }
            return hypothesis, trace
        except Exception as exc:
            last_error = str(exc)
            print(f"[planner] ERROR (attempt {attempt}/2): {exc}")
            last_trace = {
                "messages": messages,
                "context_file": str(context_file) if context_file else None,
                "model_name": provider_cfg.get("model", "unknown"),
                "provider": provider_cfg.get("provider", "unknown"),
                "attempt": attempt,
                "error": last_error,
                "iter_tag": iter_tag,
            }

    # Save error trace to artifacts
    if iter_tag:
        artifact_path = _artifact_dir(iter_tag)
        artifact_path.mkdir(parents=True, exist_ok=True)
        error_trace_file = artifact_path / "planner_error_trace.json"
        with open(error_trace_file, "w") as f:
            json.dump(last_trace, f, indent=2, default=str)
        print(f"[planner] saved error trace to {error_trace_file}")

    raise PlannerResponseError(f"planner failed after 2 attempts: {last_error}", last_trace or {})


def parse_human_directions(
    directions_text: str,
    recent_experiments: list[dict],
    provider_cfg: dict,
) -> list[dict]:
    """Parse free-form human directions into a list of structured experiment plans via direct LLM call."""
    history_text = _format_history(recent_experiments[-10:])
    user_content = (
        f"## Human Research Directions\n{directions_text}\n\n"
        f"## Recent Experiment History (for deduplication)\n{history_text}\n\n"
        "Extract the experiment plans from the human directions above."
    )
    _cfg = yaml.safe_load((AUTORESEARCH_DIR / "config.yaml").read_text())
    _model_file = _cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py")
    formatted_director_prompt = DIRECTOR_SYSTEM_PROMPT.format(model_file=_model_file)
    messages = [
        {"role": "system", "content": formatted_director_prompt},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(provider_cfg, messages)
    raw = raw.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    plans = json.loads(raw)
    if not isinstance(plans, list):
        raise ValueError(f"Expected JSON array, got: {type(plans)}")
    required = {"hypothesis", "target_component", "rationale", "instruction", "run_name"}
    valid = []
    for p in plans:
        if isinstance(p, dict) and required.issubset(p.keys()):
            valid.append(p)
        else:
            print(f"[queue] skipping plan with missing fields: {p}")
    return valid


def _build_planner_prompt(
    messages: list[dict],
    history_text: str,
    config_text: str,
    conventions_text: str,
    error_context: str | None,
) -> str:
    """Build a single prompt string for opencode that instructs it to append a hypothesis to the queue file."""
    stream_id = get_stream_id()
    _cfg = yaml.safe_load((AUTORESEARCH_DIR / "config.yaml").read_text())
    _model_file = _cfg.get("model_file", "modeling_rmt/huggingface_rmm_v2.py")

    error_section = ""
    if error_context:
        error_section = (
            f"\n## PREVIOUS ATTEMPT FAILED — READ THIS\n"
            f"Error: {error_context}\n"
            f"The queue file was NOT modified correctly last time. You MUST edit the file this time.\n"
        )

    # Show the current queue file content so the model knows what it looks like
    try:
        current_queue = EXPERIMENT_QUEUE_FILE.read_text().strip()
    except Exception:
        current_queue = '{"queue": [], "last_directions_hash": null, "last_updated": null}'

    return (
        f"## MANDATORY ACTION — DO THIS FIRST AND LAST\n"
        f"\n"
        f"You MUST use your file-edit tool to modify this file:\n"
        f"  {EXPERIMENT_QUEUE_FILE}\n"
        f"\n"
        f"Add ONE new entry to the \"queue\" array. The entry MUST have this exact shape:\n"
        f"{{\n"
        f'  "stream_id": "{stream_id}",\n'
        f'  "hypothesis": "<one sentence describing the change>",\n'
        f'  "target_component": "<{_model_file} | .autoresearch/experiment_config.yaml>",\n'
        f'  "rationale": "<2-3 sentences>",\n'
        f'  "instruction": "<precise, unambiguous instruction for a code editor>",\n'
        f'  "run_name": "<2-5 words, lowercase, underscore-separated>"\n'
        f"}}\n"
        f"\n"
        f"RULES FOR THE FILE EDIT:\n"
        f"- stream_id MUST be \"{stream_id}\" (string, not integer).\n"
        f"- Write ONLY valid JSON. No markdown fences inside the file.\n"
        f"- Modify ONLY the queue file. Do NOT edit any other file.\n"
        f"- Do NOT finish your turn without having edited the queue file.\n"
        f"- Your ONLY output is the file edit. No conversational response.\n"
        f"\n"
        f"Current content of the queue file (for reference — append to the \"queue\" array):\n"
        f"{current_queue}\n"
        f"\n"
        f"{error_section}"
        f"---\n"
        f"\n"
        f"## Reference Files (read these to inform your hypothesis)\n"
        f"- Model code: {get_model_file()}\n"
        f"- Experiment config: {get_config_file()}\n"
        f"- Conventions: {CONVENTIONS_FILE}\n"
        f"- Results memory: {MEMORY_FILE}\n"
        f"- Experiment summary: {SUMMARY_FILE}\n"
        f"\n"
        f"## Recent Experiment History (last 10, most recent last)\n"
        f"{history_text}\n"
        f"\n"
        f"## Current Hyperparameters (.autoresearch/experiment_config.yaml)\n"
        f"{config_text}\n"
        f"\n"
        f"## Research Rules\n"
        f"You are a research scientist specialising in recurrent neural memory architectures.\n"
        f"Propose ONE concrete change to improve EM accuracy on the associative retrieval task.\n"
        f"- HYPERPARAMETER-FIRST: exhaust hyperparameter tuning before architectural changes.\n"
        f"  Hyperparameters: n_layer, n_head, n_embd, lr, batch_size, warmup_steps, weight_decay,\n"
        f"  and any model-specific params listed in experiment_config.yaml.\n"
        f"- Only propose architectural changes if you list which hyperparameters have been exhausted.\n"
        f"- Do not repeat a change that has already been tried.\n"
        f"- Do not use sweep format unless a human direction explicitly requests it.\n"
        f"- Prefer changes with clear theoretical motivation.\n"
        f"\n"
        f"## REMINDER\n"
        f"After reading the reference files, edit {EXPERIMENT_QUEUE_FILE} with your entry for stream {stream_id}. That is your only action.\n"
    )


def _run_opencode_and_enqueue(
    prompt: str,
    provider_cfg: dict,
    stream_id: str,
) -> dict:
    """
    Run opencode to append a hypothesis to the shared experiment queue file.
    Uses exclusive file locking to prevent conflicts between streams.
    Returns the hypothesis dict (popped from queue by stream_id).
    """
    queue_file = EXPERIMENT_QUEUE_FILE
    queue_file.parent.mkdir(parents=True, exist_ok=True)

    # Ensure queue file exists with valid structure
    if not queue_file.exists():
        queue_file.write_text(json.dumps({"queue": [], "last_directions_hash": None, "last_updated": None}, indent=2))

    # Backup current queue for recovery
    backup_fd, backup_path = tempfile.mkstemp(suffix=".queue_backup", dir=str(AUTORESEARCH_DIR))
    os.close(backup_fd)
    try:
        with open(queue_file, "r") as f_in:
            with open(backup_path, "w") as f_out:
                f_out.write(f_in.read())

        # Acquire exclusive lock (blocks other streams)
        lock_fd = open(QUEUE_LOCK_FILE, "w")
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            model_name = provider_cfg.get("model", "")
            provider = provider_cfg.get("provider", "")
            print(f"[planner] Calling opencode with model: {model_name}")

            # Set up environment
            env = os.environ.copy()
            if provider in ("local", "cursor"):
                env["OPENAI_BASE_URL"] = _build_base_url(provider_cfg)
                env["OPENAI_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
            elif provider == "anthropic":
                env["ANTHROPIC_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "")
            elif provider == "openai":
                env["OPENAI_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "")

            result = subprocess.run(
                ["opencode", "run", "-m", model_name, prompt],
                capture_output=True,
                text=True,
                env=env,
                cwd=REPO_ROOT,
                timeout=900,
            )

            if result.returncode != 0:
                # Restore queue from backup
                with open(backup_path, "r") as f_in:
                    with open(queue_file, "w") as f_out:
                        f_out.write(f_in.read())
                raise RuntimeError(
                    f"opencode failed (rc={result.returncode}): {result.stderr[:500]}"
                )

            # Read back queue and find our entry
            with open(queue_file, "r") as f:
                queue_data = json.load(f)

            hypothesis = None
            for i, entry in enumerate(queue_data.get("queue", [])):
                if entry.get("stream_id") == stream_id:
                    hypothesis = queue_data["queue"].pop(i)
                    break

            if hypothesis is None:
                # Restore queue from backup
                with open(backup_path, "r") as f_in:
                    with open(queue_file, "w") as f_out:
                        f_out.write(f_in.read())
                raise RuntimeError(
                    f"opencode did not append a hypothesis for stream {stream_id}. "
                    f"stdout: {result.stdout[:300]}"
                )

            # Save updated queue
            queue_data["last_updated"] = datetime.now().isoformat()
            queue_file.write_text(json.dumps(queue_data, indent=2))

        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()

    finally:
        # Clean up backup
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass

    return hypothesis


def _call_opencode_planner(
    messages: list[dict],
    provider_cfg: dict,
    context_file: Path | None = None,
    error_context: str | None = None,
    recent_experiments: list[dict] | None = None,
) -> dict:
    """
    Call opencode CLI for planning. Appends hypothesis to shared experiment queue,
    then reads it back and returns the hypothesis dict.
    """
    stream_id = get_stream_id()

    # Build history and context text
    history_text = _format_history(recent_experiments[-10:] if recent_experiments else [])

    config_text = _read_text(
        get_config_file(),
        default="(missing experiment_config.yaml)",
        max_chars=MAX_CONFIG_CHARS,
    )
    conventions_text = _read_text(
        CONVENTIONS_FILE,
        default="(missing conventions.md)",
        max_chars=MAX_CONVENTIONS_CHARS,
    )

    # Inject context file content if available
    if context_file and Path(context_file).exists():
        context_content = Path(context_file).read_text()
        print(f"[planner] Using context file: {context_file}")
        history_text = f"{context_content}\n\n---\n\n{history_text}"

    prompt = _build_planner_prompt(
        messages, history_text, config_text, conventions_text, error_context,
    )

    return _run_opencode_and_enqueue(prompt, provider_cfg, stream_id)


def _format_history(experiments: list[dict]) -> str:
    if not experiments:
        return "(no experiments yet)"
    lines = []
    for e in experiments:
        verdict = e.get("verdict", "?")
        em = e.get("em_score", "?")
        desc = e.get("description", "")
        hyp = e.get("hypothesis", {})
        hyp_str = hyp.get("hypothesis", "") if isinstance(hyp, dict) else str(hyp)
        run_error = e.get("run_error")
        line = (
            f"- iter {e.get('id', '?')} | N={e.get('n_level', '?')} | "
            f"EM={em} | {verdict} | {desc}"
            + (f"\n  hypothesis: {hyp_str}" if hyp_str else "")
        )
        if run_error:
            # Extract key info from error messages for better readability
            error_preview = run_error[:200] if run_error else ""
            line += f"\n  **Error:** {error_preview}"
        lines.append(line)
    return "\n".join(lines)


def _load_human_directions() -> tuple[str, str | None]:
    """Load human directions file and return a compact view plus latest pending item."""
    if not HUMAN_DIRECTIONS_FILE.exists():
        return "(no human directions file found)", None

    content = HUMAN_DIRECTIONS_FILE.read_text()
    items = [
        match.groupdict()
        for match in HUMAN_DIRECTION_ITEM_RE.finditer(content)
    ]
    if not items:
        return _truncate_text(content.strip(), MAX_HUMAN_DIRECTIONS_CHARS), None

    rendered = "\n".join(
        f"{item['number']}. [{item['status']}] {item['title']}"
        for item in items
    )
    latest_item = next(
        (item["number"] for item in reversed(items) if item["status"] == "Pending"),
        None,
    )
    return _truncate_text(rendered, MAX_HUMAN_DIRECTIONS_CHARS), latest_item


def _read_text(path: Path, default: str = "", max_chars: int | None = None) -> str:
    if not path.exists():
        return default
    return _truncate_text(path.read_text(), max_chars)


def _truncate_text(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head]
        + "\n\n... [truncated for context budget] ...\n\n"
        + text[-keep_tail:]
    )


def _load_summary_tail() -> str:
    if not SUMMARY_FILE.exists():
        return "(no experiment summary yet)"

    summary = SUMMARY_FILE.read_text().strip()
    if not summary:
        return "(no experiment summary yet)"
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary
    return "(truncated to recent summary entries)\n" + summary[-MAX_SUMMARY_CHARS:]


def _extract_json_candidates(raw: str) -> list[dict]:
    candidates: list[tuple[int, dict, bool]] = []
    i = 0

    while i < len(raw):
        if raw[i] != "{":
            i += 1
            continue

        depth = 0
        start = i
        in_string = False
        escape = False

        for j in range(i, len(raw)):
            char = raw[j]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : j + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    is_complete = all(
                        key in parsed
                        for key in ("hypothesis", "target_component", "rationale", "instruction")
                    )
                    candidates.append((len(candidate), parsed, is_complete))
                    i = j
                    break
        i += 1

    complete = [parsed for _, parsed, is_complete in candidates if is_complete]
    if complete:
        return complete

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [parsed for _, parsed, _ in candidates]


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()

    for parsed in _extract_json_candidates(raw):
        return parsed

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw response:\n{raw[:500]}...")
