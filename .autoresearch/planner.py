"""
Planner agent.

Input  : program.md content + last N experiment entries + human_directions.md + results_memory.json
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

HUMAN_DIRECTIONS_FILE = Path(os.path.dirname(__file__)) / "human_directions.md"

SYSTEM_PROMPT = """\
You are a research scientist specialising in recurrent neural memory architectures.
Your task is to propose ONE concrete, small architectural change to the RMCA model
(Recurrent Memory with Cross-Attention) that is likely to improve its exact-match (EM)
accuracy on the associative retrieval task.

Rules:
- Propose ONLY ONE change per iteration.
- The change must be to modeling_rmt/huggingface_rmca_v3.py.
- Do not increase parameter count by more than ~20% without strong justification.
- Do not change the training script or hyperparameters.
- Prefer changes that have a clear theoretical motivation.
- Do not repeat a change that has already been tried (see experiment history).
- HUMAN PRIORITIES: Check the human_directions section. If there are pending suggestions,
  implement the most recent one unless it has already been tried. Human direction takes precedence.

Respond with ONLY a JSON object, no markdown fences, no extra text:
{
  "hypothesis": "<one sentence>",
  "target_component": "<class or method name>",
  "rationale": "<2-3 sentences>",
  "instruction": "<precise, unambiguous instruction for the code editor>"
}"""


def plan(program_md: str, recent_experiments: list[dict], provider_cfg: dict) -> dict:
    """
    Call the planner LLM and return a parsed hypothesis dict.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    history_text = _format_history(recent_experiments)
    human_directions_text = _load_human_directions()

    user_content = f"""## Research Program
{program_md}

## Human Directions (PRIORITY - implement if available)
{human_directions_text}

## Recent Experiment History (most recent last)
{history_text}

Based on the above, propose the next architectural change to try.
If human_directions contains pending suggestions, prioritize implementing the most recent untried one."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = call_llm(provider_cfg, messages, max_tokens=1024)
    return _parse_json_response(raw)


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


def _load_human_directions() -> str:
    """Load human directions file and return the pending suggestions section."""
    if not HUMAN_DIRECTIONS_FILE.exists():
        return "(no human directions file found)"
    
    content = HUMAN_DIRECTIONS_FILE.read_text()
    
    # Extract pending suggestions section
    pending_match = re.search(r'## Pending Suggestions\n\n(.*?)(?=## |\Z)', content, re.DOTALL)
    if pending_match:
        pending_text = pending_match.group(1).strip()
        if pending_text and pending_text != "(Add your ideas below. Mark as [DONE], [SKIPPED], or [FAILED] when implemented.)":
            return f"## Pending Human Suggestions\n{pending_text}\n\n## Implementation History\n\n(see below)\n" + content[content.find("## Implementation History"):]
    
    return "(no pending suggestions)"


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if the model wraps the JSON despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw response:\n{raw}")
