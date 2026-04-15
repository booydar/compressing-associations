"""
Executor agent.

Input  : hypothesis dict from planner + current target file content
Output : complete modified file content as a string

The executor applies exactly the requested change by invoking opencode against
the real workspace, but it is told explicitly which file may be modified and
which files may be inspected as read-only context.
"""
import ast
import sys
import os
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from llm_client import _build_base_url

AUTORESEARCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = AUTORESEARCH_DIR.parent
MODEL_FILE = REPO_ROOT / "modeling_rmt" / "huggingface_rmca_v3.py"
EXPERIMENT_CONFIG_FILE = AUTORESEARCH_DIR / "experiment_config.yaml"
CONVENTIONS_FILE = AUTORESEARCH_DIR / "conventions.md"
TRAINER_FILE = REPO_ROOT / "run_rmca_on_kv_retrieval-v3.py"


class ExecutorResponseError(RuntimeError):
    def __init__(self, message: str, trace: dict):
        super().__init__(message)
        self.trace = trace


def execute(
    hypothesis: dict,
    file_content: str,
    provider_cfg: dict,
    error_context: str | None = None,
    is_yaml: bool = False,
) -> str:
    return execute_with_trace(
        hypothesis,
        file_content,
        provider_cfg,
        error_context=error_context,
        is_yaml=is_yaml,
    )[0]


def execute_with_trace(
    hypothesis: dict,
    file_content: str,
    provider_cfg: dict,
    error_context: str | None = None,
    is_yaml: bool = False,
) -> tuple[str, dict]:
    """
    Call the executor LLM (via opencode) to apply the hypothesis change to the file.
    Returns the complete new file content plus trace data for logging.
    Raises SyntaxError if the returned code is not valid Python/YAML.
    """
    target = hypothesis.get("target_component", "")
    context_files = _context_files_for_target(target)
    target_path_obj = Path(target)
    if target and not target_path_obj.is_absolute():
        target_path_obj = REPO_ROOT / target_path_obj

    # Write the current content to the actual target file so opencode can modify it in place.
    # This allows opencode to see the file in its true location and look at other files.
    if not target or not target_path_obj.exists():
        # Fallback to a temp file if target doesn't exist (e.g. in some tests)
        suffix = ".yaml" if is_yaml else ".py"
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=suffix, dir=str(REPO_ROOT)) as temp_file:
            temp_file.write(file_content)
            target_path = temp_file.name
        is_temp = True
        original_disk_content = None
    else:
        target_path = str(target_path_obj)
        is_temp = False
        with open(target_path, 'r') as f:
            original_disk_content = f.read()
        with open(target_path, 'w') as f:
            f.write(file_content)

    abs_target_path = os.path.abspath(target_path)
    prompt = _build_executor_prompt(
        hypothesis=hypothesis,
        editable_file=abs_target_path,
        context_files=context_files,
        error_context=error_context,
    )

    try:
        # Prepare environment for opencode
        env = os.environ.copy()
        
        provider = provider_cfg.get("provider", "")
        model_name = provider_cfg.get("model", "")

        if provider in ("local", "cursor"):
            env["OPENAI_BASE_URL"] = _build_base_url(provider_cfg)
            env["OPENAI_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "no-key") or "no-key"
        elif provider == "anthropic":
            env["ANTHROPIC_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "")
        elif provider == "openai":
            env["OPENAI_API_KEY"] = os.environ.get(provider_cfg.get("api_key_env", ""), "")

        # Call opencode
        print(f"[executor] Calling opencode with model: {model_name}")
        result = subprocess.run(
            ["opencode", "run", "-m", model_name, prompt],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
        )

        trace = {
            "hypothesis": hypothesis,
            "prompt": prompt,
            "editable_file": abs_target_path,
            "context_files": context_files,
            "cwd": str(REPO_ROOT),
            "model_name": model_name,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

        if result.returncode != 0:
            print(f"[executor] opencode failed with return code {result.returncode}")
            print(f"[executor] opencode stderr:\n{result.stderr}")
            raise ExecutorResponseError(f"opencode failed: {result.stderr}", trace)

        # Read the modified content
        with open(target_path, 'r') as f:
            content = f.read()

        if is_yaml:
            _validate_yaml(content)
        else:
            _validate_syntax(content)

        trace["result_preview"] = content[:500]
        return content, trace

    except Exception as exc:
        if isinstance(exc, ExecutorResponseError):
            raise
        trace = {
            "hypothesis": hypothesis,
            "prompt": prompt,
            "editable_file": abs_target_path,
            "context_files": context_files,
            "cwd": str(REPO_ROOT),
        }
        raise ExecutorResponseError(str(exc), trace) from exc
        
    finally:
        # Clean up or restore
        if is_temp:
            if os.path.exists(target_path):
                os.remove(target_path)
        else:
            # Restore the file to its original state so we don't leave it broken
            # autoresearch.py will write the new content if validation passes.
            if original_disk_content is not None:
                with open(target_path, 'w') as f:
                    f.write(original_disk_content)


def _build_executor_prompt(
    hypothesis: dict,
    editable_file: str,
    context_files: list[str],
    error_context: str | None = None,
) -> str:
    instruction = hypothesis.get("instruction", "")
    rationale = hypothesis.get("rationale", "")
    target = hypothesis.get("target_component", "")

    context_block = "\n".join(f"- {path}" for path in context_files)
    error_section = ""
    if error_context:
        error_section = f"\n## Previous attempt failed\n{error_context}\n"

    return f"""## Change to implement
Target component: {target}
Editable file: {editable_file}
Rationale: {rationale}
Instruction: {instruction}
{error_section}

## File access rules
- Modify ONLY the editable file above.
- You may inspect these files for context if needed:
{context_block}
- Run from repo root: {REPO_ROOT}
- Do not edit any other file.
- Keep the change minimal and directly targeted.
"""


def _context_files_for_target(target: str) -> list[str]:
    files = {
        str(MODEL_FILE.resolve()),
        str(EXPERIMENT_CONFIG_FILE.resolve()),
        str(CONVENTIONS_FILE.resolve()),
        str(TRAINER_FILE.resolve()),
    }
    if target:
        files.add(str(Path(target).resolve()))
    return sorted(files)


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
