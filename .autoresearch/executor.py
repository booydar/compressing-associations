"""
Executor agent.

Input  : hypothesis dict from planner + current model file content
Output : complete modified model file as a string

The executor receives a precise instruction and the full current model file,
applies exactly the requested change, and returns the complete new file.
It does NOT see experiment history — it only knows what to change and the code.
"""
import ast
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from llm_client import call_llm

SYSTEM_PROMPT = """\
You are an expert PyTorch engineer.
You will receive:
1. A precise instruction describing ONE architectural change to make.
2. The complete current content of the model file.

Your task: apply EXACTLY the described change and return the COMPLETE modified file.

Rules:
- Return ONLY the raw Python source code of the modified file. No markdown fences,
  no explanation, no extra text before or after.
- Make ONLY the change described. Do not refactor unrelated code.
- Preserve all imports, class names, and method signatures unless the change
  explicitly requires modifying them.
- The returned file must be syntactically valid Python."""


def execute(
    hypothesis: dict,
    model_file_content: str,
    provider_cfg: dict,
    error_context: str | None = None,
) -> str:
    """
    Call the executor LLM to apply the hypothesis change to the model file.
    Returns the complete new file content as a string.
    Raises SyntaxError if the returned code is not valid Python.

    error_context: if a previous attempt failed, pass the error message here so
                   the LLM can fix the specific issue.
    """
    instruction = hypothesis.get("instruction", "")
    rationale = hypothesis.get("rationale", "")
    target = hypothesis.get("target_component", "")

    error_section = ""
    if error_context:
        error_section = f"\n## Previous attempt failed — fix this\n{error_context}\n"

    user_content = f"""## Change to implement
Target component: {target}
Rationale: {rationale}
Instruction: {instruction}
{error_section}
## Current model file (modeling_rmt/huggingface_rmca_v3.py)
```python
{model_file_content}
```

Return the complete modified file."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = call_llm(provider_cfg, messages, max_tokens=32000)
    code = _strip_fences(raw)
    _validate_syntax(code)
    return code


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _validate_syntax(code: str) -> None:
    """Raise SyntaxError with a descriptive message if code is not valid Python."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise SyntaxError(
            f"Executor returned syntactically invalid Python: {e}\n"
            f"Offending line {e.lineno}: {e.text}"
        )
