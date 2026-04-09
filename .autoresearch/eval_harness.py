"""
Read experiment results written by trainer.save_metrics(split='all', ...).
Returns exact_match and token_accuracy for a completed experiment.
"""
import json
from pathlib import Path


def get_metrics(exp_path: str) -> dict:
    """
    Parse all_results.json from the experiment directory.

    Returns a dict with at least:
      exact_match    : float   (primary metric)
      token_accuracy : float

    Raises FileNotFoundError if the file does not exist (experiment didn't finish).
    """
    p = Path(exp_path) / "all_results.json"
    if not p.exists():
        raise FileNotFoundError(
            f"all_results.json not found in {exp_path}. "
            "Did the experiment finish? Check trainer.save_metrics() was called."
        )
    data = json.loads(p.read_text())

    em = data.get("eval_exact_match")
    if em is None:
        raise KeyError(
            f"'eval_exact_match' not found in {p}. "
            f"Available keys: {list(data.keys())}"
        )

    return {
        "exact_match": float(em),
        "token_accuracy": float(data.get("eval_token_accuracy", float("nan"))),
        "raw": data,
    }


def get_em(exp_path: str) -> float:
    """Convenience wrapper — returns just the exact_match float."""
    return get_metrics(exp_path)["exact_match"]
