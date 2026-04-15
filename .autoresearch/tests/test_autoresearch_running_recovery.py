import importlib.util
import sys
import types
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
AUTORESEARCH_DIR = TESTS_DIR.parent


def _load_autoresearch_module():
    planner_stub = types.ModuleType("planner")
    planner_stub.plan = lambda *args, **kwargs: None
    sys.modules["planner"] = planner_stub

    executor_stub = types.ModuleType("executor")
    executor_stub.execute = lambda *args, **kwargs: None
    executor_stub._validate_yaml = lambda *args, **kwargs: None
    sys.modules["executor"] = executor_stub

    eval_stub = types.ModuleType("eval_harness")
    eval_stub.get_metrics = lambda *args, **kwargs: None
    sys.modules["eval_harness"] = eval_stub

    spec = importlib.util.spec_from_file_location(
        "autoresearch_under_test",
        AUTORESEARCH_DIR / "autoresearch.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_running_entry_is_recovered_before_planning(monkeypatch, tmp_path):
    autoresearch = _load_autoresearch_module()
    monkeypatch.setattr(autoresearch, "RESEARCH_LOG", tmp_path / "research_log.md")
    monkeypatch.setattr(autoresearch, "PROGRAM_MD", tmp_path / "program.md")
    monkeypatch.setattr(autoresearch, "update_program_md", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        autoresearch,
        "get_metrics",
        lambda exp_path: {
            "exact_match": 0.44,
            "token_accuracy": 0.77,
            "step": 1200,
            "source": "trainer_state",
            "is_partial": True,
        },
    )

    memory = {
        "current_best": {"variant": "baseline", "em": 0.30, "n_level": 2},
        "n_level": 2,
        "experiments": [],
    }
    entry = autoresearch._record_running_iter(
        memory=memory,
        iter_id=3,
        iter_tag="iter_003",
        n_level=2,
        current_best_em=0.30,
        description="test hypothesis",
        exp_path=str(tmp_path / "iter_003"),
        hypothesis={"target_component": "modeling_rmt/huggingface_rmca_v3.py"},
    )

    reverted = []
    monkeypatch.setattr(autoresearch, "_revert_entry_change", lambda pending: reverted.append(pending["id"]))

    recovered, unresolved = autoresearch._reconcile_running_entries(memory, {"em_threshold": 0.99})

    assert recovered == 1
    assert unresolved == 0
    assert reverted == []
    assert entry["status"] == "completed"
    assert entry["verdict"] == "kept"
    assert entry["em_score"] == 0.44
    assert entry["metric_source"] == "trainer_state"
    assert entry["is_partial"] is True
    assert entry["needs_retry"] is False
    assert memory["current_best"]["variant"] == "iter_003"
    assert memory["current_best"]["em"] == 0.44


def test_running_entry_without_metrics_is_marked_for_retry(monkeypatch, tmp_path):
    autoresearch = _load_autoresearch_module()
    monkeypatch.setattr(autoresearch, "RESEARCH_LOG", tmp_path / "research_log.md")
    monkeypatch.setattr(autoresearch, "PROGRAM_MD", tmp_path / "program.md")
    monkeypatch.setattr(autoresearch, "update_program_md", lambda *args, **kwargs: None)

    def raise_missing(exp_path):
        raise FileNotFoundError("no checkpoints yet")

    monkeypatch.setattr(autoresearch, "get_metrics", raise_missing)

    memory = {
        "current_best": {"variant": "baseline", "em": 0.30, "n_level": 2},
        "n_level": 2,
        "experiments": [],
    }
    entry = autoresearch._record_running_iter(
        memory=memory,
        iter_id=4,
        iter_tag="iter_004",
        n_level=2,
        current_best_em=0.30,
        description="another hypothesis",
        exp_path=str(tmp_path / "iter_004"),
        hypothesis={"target_component": "modeling_rmt/huggingface_rmca_v3.py"},
    )

    recovered, unresolved = autoresearch._reconcile_running_entries(memory, {"em_threshold": 0.99})

    assert recovered == 0
    assert unresolved == 1
    assert entry["status"] == "failed"
    assert entry["verdict"] == "failed"
    assert entry["needs_retry"] is True
    assert entry["recovery_status"] == "unresolved"
