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
You are an expert engineer. You will receive:
1. A precise instruction describing ONE change to make.
2. The complete current file content.

The change may be to:
- A Python model file (modeling_rmt/huggingface_rmca_v3.py) - return Python code
- A YAML config file (.autoresearch/experiment_config.yaml) - return YAML content

Your task: apply EXACTLY the described change and return the COMPLETE modified file.

Rules:
- Return ONLY the raw content of the modified file. No markdown fences,
  no explanation, no extra text before or after.
- Make ONLY the change described. Do not refactor unrelated code.
- For Python: preserve all imports, class names, and method signatures unless the change
  explicitly requires modifying them. The file must be syntactically valid.
- For YAML: preserve the structure and comments. Only modify the requested parameter(s)."""


def execute(
    hypothesis: dict,
    file_content: str,
    provider_cfg: dict,
    error_context: str | None = None,
    is_yaml: bool = False,
) -> str:
    """
    Call the executor LLM to apply the hypothesis change to the file.
    Returns the complete new file content as a string.
    Raises SyntaxError if the returned code is not valid Python/YAML.

    error_context: if a previous attempt failed, pass the error message here so
                   the LLM can fix the specific issue.
    is_yaml: if True, validate as YAML instead of Python.
    """
    instruction = hypothesis.get("instruction", "")
    rationale = hypothesis.get("rationale", "")
    target = hypothesis.get("target_component", "")

    error_section = ""
    if error_context:
        error_section = f"\n## Previous attempt failed — fix this\n{error_context}\n"

    file_type = "YAML" if is_yaml else "Python"
    user_content = f"""## Change to implement
Target component: {target}
Rationale: {rationale}
Instruction: {instruction}
{error_section}
## Current file content
```{file_type.lower()}
{file_content}
```

Return the complete modified file."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw = call_llm(provider_cfg, messages, max_tokens=32000)
    content = _strip_fences(raw)
    if is_yaml:
        _validate_yaml(content)
    else:
        _validate_syntax(content)
    return content


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


def _validate_yaml(yaml_content: str) -> None:
    """Raise ValueError with a descriptive message if content is not valid YAML."""
    try:
        import yaml as yaml_lib
        yaml_lib.safe_load(yaml_content)
    except Exception as e:
        raise ValueError(
            f"Executor returned invalid YAML: {e}\n"
            f"Content preview: {yaml_content[:200]}"
        )
