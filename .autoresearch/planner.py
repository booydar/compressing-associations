"""
Planner agent.

Input  : current model/config context + experiment summary + last N experiment entries
Output : a JSON hypothesis dict:
  {
    "hypothesis": "One-sentence description of the proposed change",
    "target_component": "MemoryAugmentedLayer | RMCACell | RMCAWrapperBase | ...",
    "rationale": "Why this change should improve EM on the associative retrieval task",
    "instruction": "Precise instruction for the executor: what to add/change/remove in the model file"
  }
"""
import json
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from llm_client import call_llm

AUTORESEARCH_DIR = Path(os.path.dirname(__file__))
REPO_ROOT = AUTORESEARCH_DIR.parent
HUMAN_DIRECTIONS_FILE = AUTORESEARCH_DIR / "human_directions.md"
SUMMARY_FILE = AUTORESEARCH_DIR / "experiment_summary.md"
EXPERIMENT_CONFIG_FILE = AUTORESEARCH_DIR / "experiment_config.yaml"
CONVENTIONS_FILE = AUTORESEARCH_DIR / "conventions.md"
MODEL_FILE = REPO_ROOT / "modeling_rmt" / "huggingface_rmca_v3.py"
MAX_SUMMARY_CHARS = 12000
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
Your task is to propose ONE concrete change to improve the RMCA model's
(Recurrent Memory with Cross-Attention) exact-match (EM) accuracy on the associative retrieval task.

You may propose changes to:
1. **Architecture** - modifications to modeling_rmt/huggingface_rmca_v3.py
2. **Model hyperparameters** - n_layer, n_head, n_embd, n_mem_tokens (in .autoresearch/experiment_config.yaml)
3. **Training hyperparameters** - learning rate, optimizer, batch size, warmup steps, etc. (in .autoresearch/experiment_config.yaml)

CRITICAL RULES:
- HUMAN DIRECTIONS TAKE ABSOLUTE PRIORITY: If human_directions.md contains pending suggestions,
  you MUST implement the most recent untried suggestion from that list before proposing anything else.
- HYPERPARAMETER-FIRST POLICY: You are REQUIRED to exhaust hyperparameters tuning before architectural changes.
  Hyperparameters include: n_layer, n_head, n_embd, n_mem_tokens, lr, batch_size, warmup_steps,
  optimizer, weight_decay, max_steps, temperature, dropout rates.
- ONLY propose architectural changes if:
  (a) All pending human suggestions (hyperparameters) have been marked [Done] or [Skipped], AND
  (b) You explicitly list which hyperparameters have been exhausted and why further tuning won't help.
- Propose ONLY ONE change per iteration.
- For architectural changes: target modeling_rmt/huggingface_rmca_v3.py.
- For hyperparameters changes: target .autoresearch/experiment_config.yaml.
- Do not increase total parameter count by more than ~50% without strong justification.
- Prefer changes that have a clear theoretical motivation.
- Do not repeat a change that has already been tried (see experiment history).
- IF implementing a human_directions item: set "human_directions_item" to the numbered item you are implementing.

In your rationale, you MUST explicitly state:
- If proposing hyperparameters: which specific values/ranges you are exploring
- If proposing architecture: which hyperparameters have been exhausted and why further tuning won't help
- If implementing a human_directions item: reference which numbered item you are addressing

Respond with ONLY a JSON object, no markdown fences, no extra text:
{
  "hypothesis": "<one sentence>",
  "target_component": "<modeling_rmt/huggingface_rmca_v3.py | .autoresearch/experiment_config.yaml>",
  "rationale": "<2-3 sentences, MUST mention hyperparameters status if proposing architecture>",
  "instruction": "<precise, unambiguous instruction for the code editor>",
  "human_directions_item": "<item number or null if not implementing a human suggestion>"
}"""


class PlannerResponseError(ValueError):
    def __init__(self, message: str, trace: dict):
        super().__init__(message)
        self.trace = trace


def build_planner_messages(
    program_md: str,
    recent_experiments: list[dict],
    error_context: str | None = None,
) -> list[dict]:
    del program_md  # intentionally unused to keep planner context bounded

    history_text = _format_history(recent_experiments[-10:])
    human_directions_text, latest_pending_item = _load_human_directions()
    experiment_summary = _load_summary_tail()
    config_text = _read_text(
        EXPERIMENT_CONFIG_FILE,
        default="(missing experiment_config.yaml)",
        max_chars=MAX_CONFIG_CHARS,
    )
    conventions_text = _read_text(
        CONVENTIONS_FILE,
        default="(missing conventions.md)",
        max_chars=MAX_CONVENTIONS_CHARS,
    )
    model_text = _read_text(
        MODEL_FILE,
        default="(missing modeling_rmt/huggingface_rmca_v3.py)",
        max_chars=MAX_MODEL_CHARS,
    )

    user_content = f"""## Human Directions (PRIORITY - implement if available)
{human_directions_text}
Latest pending item to implement: {latest_pending_item if latest_pending_item else "(none)"}

## Experiment Summary
{experiment_summary}

## Recent Experiment History (last 10, most recent last)
{history_text}

## Current Hyperparameters (.autoresearch/experiment_config.yaml)
{config_text}

## Repository Conventions
{conventions_text}

## Current Model Architecture (modeling_rmt/huggingface_rmca_v3.py)
{model_text}

Based on the above, propose the next change to try (either architectural or hyperparameter, strictly following the priorities above).
If human_directions contains pending suggestions, prioritize implementing item #{latest_pending_item if latest_pending_item else "the most recent pending"}.
Set "human_directions_item" to the item number you are implementing."""

    if error_context:
        user_content += (
            "\n\n## Previous Attempt Failed\n"
            "Your previous response failed to parse as JSON or violated the required schema.\n"
            f"Error: {error_context}\n"
            "Please ensure your response is ONLY a valid JSON object."
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def plan_with_trace(
    program_md: str,
    recent_experiments: list[dict],
    provider_cfg: dict,
    error_context: str | None = None,
) -> tuple[dict, dict]:
    """
    Call the planner LLM and return both parsed hypothesis and trace data.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    messages = build_planner_messages(program_md, recent_experiments, error_context=error_context)
    raw = call_llm(provider_cfg, messages, max_tokens=8192)
    trace = {
        "messages": messages,
        "raw_response": raw,
    }
    try:
        parsed = _parse_json_response(raw)
    except Exception as exc:
        trace["parse_error"] = str(exc)
        raise PlannerResponseError(str(exc), trace) from exc
    trace["parsed_response"] = parsed
    return parsed, trace


def plan(program_md: str, recent_experiments: list[dict], provider_cfg: dict, error_context: str | None = None) -> dict:
    return plan_with_trace(program_md, recent_experiments, provider_cfg, error_context=error_context)[0]


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
        lines.append(
            f"- iter {e.get('id', '?')} | N={e.get('n_level', '?')} | "
            f"EM={em} | {verdict} | {desc}"
            + (f"\n  hypothesis: {hyp_str}" if hyp_str else "")
        )
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
