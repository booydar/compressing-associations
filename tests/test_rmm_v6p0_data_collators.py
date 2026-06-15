"""Unit tests for the RMM v6p0 dataset collators (babi / squad / lm).

Pure-python — no `fla`/CUDA needed (the runners import the model lazily inside
build_rmm_model, so importing the module only needs torch/transformers). Loads
each runner via importlib and injects the module globals (`tokenizer`, `args`)
its collate_fn expects, exactly like tests/leak_test_v6p0.py does.

Checks the RMT->RMM 2-segment mapping:
  segments = [context_seg, qt_seg]
and that labels / labels_mask are placed for RMM's predict-next shift (position p
is in the loss iff p+1 is a labelled token).

Run:
    cd ~/rmt/test-time/compressing-associations-gdn
    ~/envs/fla/bin/python tests/test_rmm_v6p0_data_collators.py
"""
import os
import sys
import types
import importlib.util

import torch
from transformers import AutoTokenizer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _load_runner(filename, tokenizer, args_ns):
    name = filename.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, filename))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.tokenizer = tokenizer
    runner.args = args_ns
    return runner


def _check_segment_keys(seg):
    for k in ("input_ids", "attention_mask", "labels", "labels_mask"):
        assert k in seg, f"segment missing key {k}"
    B, L = seg["input_ids"].shape
    for k in ("attention_mask", "labels", "labels_mask"):
        assert seg[k].shape == (B, L), f"{k} shape {seg[k].shape} != {(B, L)}"
    assert seg["labels_mask"].dtype == torch.bool


def test_squad_like(tokenizer):
    """squad/babi share the same collator; test via the squad runner."""
    args_ns = types.SimpleNamespace(max_context_length=None)
    runner = _load_runner("run_rmm_on_squad-v6p0.py", tokenizer, args_ns)

    batch = [
        {"context": "The capital of France is Paris. It is large.",
         "query": "What is the capital? ", "target": "Paris"},
        {"context": "Mary went to the kitchen then the garden.",
         "query": "Where is Mary? ", "target": "garden"},
    ]
    out = runner.collate_fn(batch)
    assert set(out.keys()) == {"segments", "labels"}
    segs = out["segments"]
    assert len(segs) == 2, f"expected 2 segments, got {len(segs)}"
    ctx_seg, qt_seg = segs
    _check_segment_keys(ctx_seg)
    _check_segment_keys(qt_seg)

    # context segment: never in the loss
    assert (ctx_seg["labels"] == -100).all(), "context labels must be all -100"
    assert (~ctx_seg["labels_mask"]).all(), "context labels_mask must be all False"

    # qt segment: each sample has >=1 labelled target token
    for i, item in enumerate(batch):
        labelled = (qt_seg["labels"][i] != -100)
        assert labelled.any(), f"sample {i}: no target tokens labelled"
        # labelled positions must decode to (a superset containing) the target text
        tok_ids = qt_seg["input_ids"][i][labelled]
        decoded = tokenizer.decode(tok_ids).strip()
        assert item["target"] in decoded or decoded in item["target"], \
            f"sample {i}: labelled tokens {decoded!r} vs target {item['target']!r}"
        # predict-next alignment: every loss position p predicts a labelled token at p+1
        lm = qt_seg["labels_mask"][i]
        lab = qt_seg["labels"][i]
        for p in torch.where(lm)[0].tolist():
            assert p + 1 < lab.shape[0] and lab[p + 1] != -100, \
                f"sample {i}: labels_mask at {p} does not predict a labelled token"
        assert int(lm.sum()) == int(labelled.sum()), \
            "loss positions should match labelled-target count (interior target)"

    # full labels = concat of the two segments
    assert out["labels"].shape[1] == ctx_seg["labels"].shape[1] + qt_seg["labels"].shape[1]
    print("[ok] squad/babi collator: 2 segments, target labels + shifted loss mask")


def test_lm(tokenizer):
    context_size, segment_size = 4, 4
    full_len = context_size + segment_size
    args_ns = types.SimpleNamespace(context_size=context_size, segment_size=segment_size)
    runner = _load_runner("run_rmm_on_lm-v6p0.py", tokenizer, args_ns)

    # two full windows of length context_size+segment_size
    w0 = list(range(10, 10 + full_len))
    w1 = list(range(100, 100 + full_len))
    batch = [{"input_ids": w0}, {"input_ids": w1}]
    out = runner.collate_fn(batch)
    segs = out["segments"]
    assert len(segs) == 2
    ctx_seg, qt_seg = segs
    _check_segment_keys(ctx_seg)
    _check_segment_keys(qt_seg)

    # RMT assignment: context = window[context_size:], qt = window[:context_size]
    assert ctx_seg["input_ids"][0].tolist() == w0[context_size:], "context must be the later half"
    assert qt_seg["input_ids"][0].tolist() == w0[:context_size], "qt must be the earlier half"

    # LM loss is on the qt (earlier-half) tokens, never on context
    assert (ctx_seg["labels"] == -100).all()
    assert (qt_seg["labels"][0].tolist() == w0[:context_size]), "qt labels are the qt tokens"

    # predict-next mask over the full concat: True iff next token is labelled (non -100)
    full_labels = out["labels"]
    full_mask = torch.cat([ctx_seg["labels_mask"], qt_seg["labels_mask"]], dim=1)
    for i in range(full_labels.shape[0]):
        for p in range(full_labels.shape[1] - 1):
            expect = bool(full_labels[i, p + 1] != -100)
            assert bool(full_mask[i, p]) == expect, f"lm mask mismatch at {(i, p)}"
        assert not bool(full_mask[i, -1]), "last position can never be a loss position"
    # boundary: last context token predicts first qt token -> in the loss
    assert bool(ctx_seg["labels_mask"][0, -1]), "context->qt boundary should be a loss position"
    print("[ok] lm collator: reversed context/qt halves, boundary + within-qt loss mask")


def main():
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    test_squad_like(tokenizer)
    test_lm(tokenizer)
    print("\nAll collator tests passed.")


if __name__ == "__main__":
    main()
