import json
import math
import sys
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
AUTORESEARCH_DIR = TESTS_DIR.parent
sys.path.insert(0, str(AUTORESEARCH_DIR))

from eval_harness import get_metrics


def test_get_metrics_prefers_all_results(tmp_path):
    exp_dir = tmp_path / "iter_001"
    exp_dir.mkdir()
    (exp_dir / "all_results.json").write_text(json.dumps({
        "eval_exact_match": 0.42,
        "eval_token_accuracy": 0.84,
        "step": 1234,
    }))

    checkpoint_dir = exp_dir / "checkpoint-1000"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "trainer_state.json").write_text(json.dumps({
        "global_step": 1000,
        "log_history": [
            {"step": 1000, "eval_exact_match": 0.11, "eval_token_accuracy": 0.22},
        ],
    }))

    metrics = get_metrics(str(exp_dir))

    assert metrics["exact_match"] == 0.42
    assert metrics["token_accuracy"] == 0.84
    assert metrics["step"] == 1234
    assert metrics["source"] == "all_results"
    assert metrics["is_partial"] is False


def test_get_metrics_recovers_best_eval_from_trainer_state(tmp_path):
    exp_dir = tmp_path / "iter_002"
    exp_dir.mkdir()

    checkpoint_dir = exp_dir / "checkpoint-2500"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "trainer_state.json").write_text(json.dumps({
        "best_global_step": 2000,
        "global_step": 2500,
        "log_history": [
            {"step": 500, "eval_exact_match": 0.10, "eval_token_accuracy": 0.30},
            {"step": 1500, "eval_exact_match": 0.25, "eval_token_accuracy": 0.55},
            {"step": 2000, "eval_exact_match": 0.40, "eval_token_accuracy": 0.70},
            {"step": 2500, "loss": 1.23},
        ],
    }))

    metrics = get_metrics(str(exp_dir))

    assert metrics["exact_match"] == 0.40
    assert metrics["token_accuracy"] == 0.70
    assert metrics["step"] == 2000
    assert metrics["source"] == "trainer_state"
    assert metrics["is_partial"] is True
    assert metrics["checkpoint_dir"].endswith("checkpoint-2500")


def test_get_metrics_raises_when_no_results_exist(tmp_path):
    exp_dir = tmp_path / "iter_003"
    exp_dir.mkdir()

    checkpoint_dir = exp_dir / "checkpoint-500"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "trainer_state.json").write_text(json.dumps({
        "global_step": 500,
        "log_history": [
            {"step": 500, "eval_exact_match": None},
            {"step": 500, "eval_exact_match": math.nan},
        ],
    }))

    try:
        get_metrics(str(exp_dir))
    except FileNotFoundError as exc:
        assert "Could not recover metrics from checkpoints" in str(exc)
    else:
        raise AssertionError("Expected get_metrics() to fail without recoverable eval metrics")
