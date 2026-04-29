"""
Read experiment metrics from the final JSON when available, otherwise recover
them from the latest surviving trainer checkpoint.
"""
import json
import math
from pathlib import Path


def _is_valid_metric(value) -> bool:
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _checkpoint_step(path: Path) -> int:
    try:
        return int(path.name.split("-")[-1])
    except ValueError:
        return -1


def _get_metrics_from_all_results(exp_dir: Path) -> dict:
    p = exp_dir / "all_results.json"
    if not p.exists():
        raise FileNotFoundError(f"all_results.json not found in {exp_dir}")

    data = json.loads(p.read_text())
    em = data.get("eval_exact_match")
    if not _is_valid_metric(em):
        raise KeyError(
            f"'eval_exact_match' not found in {p}. "
            f"Available keys: {list(data.keys())}"
        )

    return {
        "exact_match": float(em),
        "token_accuracy": float(data.get("eval_token_accuracy", float("nan"))),
        "step": int(data.get("step", 0) or 0),
        "source": "all_results",
        "is_partial": False,
        "raw": data,
    }


def _get_metrics_from_trainer_state(exp_dir: Path) -> dict:
    checkpoints = sorted(exp_dir.glob("checkpoint-*"), key=_checkpoint_step, reverse=True)
    if not checkpoints:
        raise FileNotFoundError(f"No checkpoints found in {exp_dir}")

    state_errors = []
    for checkpoint_dir in checkpoints:
        state_path = checkpoint_dir / "trainer_state.json"
        if not state_path.exists():
            continue

        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError as exc:
            state_errors.append(f"{state_path}: invalid JSON ({exc})")
            continue

        eval_logs = [
            log for log in state.get("log_history", [])
            if _is_valid_metric(log.get("eval_exact_match"))
        ]
        if not eval_logs:
            state_errors.append(f"{state_path}: no eval_exact_match in log_history")
            continue

        best_eval = max(
            eval_logs,
            key=lambda log: (
                float(log["eval_exact_match"]),
                int(log.get("step", 0) or 0),
            ),
        )
        return {
            "exact_match": float(best_eval["eval_exact_match"]),
            "token_accuracy": float(best_eval.get("eval_token_accuracy", float("nan"))),
            "step": int(
                best_eval.get("step")
                or state.get("best_global_step")
                or state.get("best_step")
                or state.get("global_step")
                or _checkpoint_step(checkpoint_dir)
                or 0
            ),
            "source": "trainer_state",
            "is_partial": True,
            "checkpoint_dir": str(checkpoint_dir),
            "raw": state,
        }

    error_text = "; ".join(state_errors) if state_errors else "no readable trainer_state.json files"
    raise FileNotFoundError(f"Could not recover metrics from checkpoints in {exp_dir}: {error_text}")


def get_metrics(exp_path: str) -> dict:
    """
    Return experiment metrics from final results when present, otherwise recover
    them from checkpoint trainer state.
    """
    exp_dir = Path(exp_path)

    try:
        return _get_metrics_from_all_results(exp_dir)
    except FileNotFoundError:
        return _get_metrics_from_trainer_state(exp_dir)


def get_em(exp_path: str) -> float:
    """Convenience wrapper — returns just the exact_match float."""
    return get_metrics(exp_path)["exact_match"]
