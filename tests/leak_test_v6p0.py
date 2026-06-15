"""Leak diagnostic for v6p0 identity-read (check #2, causal).

Loads a trained identity_pool checkpoint and measures base exact-match (EM) on
the valid set in two conditions:

  (A) normal               — control, should reproduce the logged ~0.979 EM.
  (B) cache zeroed pre-QT   — every per-layer GDN cache is reset to empty right
                              after the context prefill and before the QT
                              segment, so the query/target segment reads a ZERO
                              memory state.

Interpretation:
  * EM collapses to ~chance under (B)  => QT retrieval flows genuinely through
    the carried recurrent state; there is no alternate path feeding the answer
    to QT. Combined with step-0 EM == 0 (check #1) => NO leak; the v6p1 split is
    unnecessary for correctness.
  * EM stays high under (B)            => the answer reaches QT without the
    memory state -> real bypass; hunt that, the split won't fix it.

Run:
    cd ~/rmt/test-time/compressing-associations-gdn
    CUDA_VISIBLE_DEVICES=0 ~/envs/fla/bin/python tests/leak_test_v6p0.py
"""
import os
import sys
import json
import types
import importlib.util

import torch
from torch.utils.data import DataLoader
import datasets
from transformers import AutoTokenizer, LlamaConfig

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from modeling_rmt.huggingface_rmm_v6p0 import (
    RecurrentMemoryBase, RecurrentMemoryConfig, RecurrentMemoryCell,
)
from fla.models.utils import Cache

CKPT = os.path.join(
    ROOT,
    "runs-rmmv6p0/N8-K2V2-V62_1M/"
    "rmmv6p0_GatedDeltaNet_llama_L4H4D128_ss32_M8_identity_pool_lr3e-04_bs64_pps1_tps7/"
    "run_1/checkpoint-9500",
)
DATA = os.path.join(ROOT, "data/N8-K2V2-V62_1M")
TOK = os.path.join(ROOT, "tokenizers/kv_alphabet_62")
N_EVAL = 1024
BS = 64
DEVICE = "cuda"


def _load_collate(tokenizer):
    """Import the runner module (main is __name__-guarded) and reuse its
    collate_fn, injecting the module globals it expects."""
    spec = importlib.util.spec_from_file_location(
        "runner_v6p0", os.path.join(ROOT, "run_rmm_on_kv_retrieval-v6p0.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.tokenizer = tokenizer
    runner.args = types.SimpleNamespace(
        memory_task_freq=0.0, memory_task=None, tokens_per_segment=7,
        memory_key_size=2, memory_value_size=2,
    )
    return runner.collate_fn


def _build_model():
    cfg = json.load(open(os.path.join(CKPT, "config.json")))
    base = LlamaConfig(**cfg["base_model_config"])
    rmm_config = RecurrentMemoryConfig(
        base_model_config=base,
        fla_layer_name=cfg["fla_layer_name"], num_heads=cfg["num_heads"],
        head_dim=cfg["head_dim"], expand_v=cfg["expand_v"],
        conv_size=cfg["conv_size"], use_short_conv=cfg["use_short_conv"],
        state_size=cfg["state_size"], num_memory_vectors=cfg["num_memory_vectors"],
        write_mode=cfg["write_mode"], read_mode=cfg["read_mode"],
        write_value_dim=cfg["write_value_dim"], num_memory_heads=cfg["num_memory_heads"],
        use_parallel_prefill=cfg["use_parallel_prefill"], max_n_segments=cfg["max_n_segments"],
        think_token_id=cfg["think_token_id"], answer_token_id=cfg["answer_token_id"],
        bos_token_id=cfg["bos_token_id"], eos_token_id=cfg["eos_token_id"],
    )
    model = RecurrentMemoryBase(rmm_config).to(DEVICE).eval()
    from safetensors.torch import load_model
    missing, unexpected = load_model(
        model, os.path.join(CKPT, "model.safetensors"), strict=False, device=DEVICE)
    print(f"loaded weights | missing={len(missing)} unexpected={len(unexpected)}")
    return model


def _em(model, dl, ignore_ids, zero_cache_pre_qt):
    """Base exact-match over dl. If zero_cache_pre_qt, reset every layer's GDN
    cache right after the context prefill (in parallel_forward) so QT reads a
    zero state."""
    orig_pf = RecurrentMemoryCell.parallel_forward
    if zero_cache_pre_qt:
        def patched_pf(self, *a, **k):
            out = orig_pf(self, *a, **k)
            for layer in RecurrentMemoryCell._get_transformer_layers(self.model):
                layer.cache = Cache()          # wipe context state before QT
            return out
        RecurrentMemoryCell.parallel_forward = patched_pf

    correct = total = 0
    try:
        with torch.no_grad():
            for batch in dl:
                segs = [{k: v.to(DEVICE) for k, v in s.items()} for s in batch["segments"]]
                labels = batch["labels"].to(DEVICE)
                logits = model(segments=segs, labels=labels)["logits"]
                pred = logits[:, :-1].argmax(-1)
                lab = labels[:, 1:]
                mask = (lab != -100)
                for t in ignore_ids:
                    mask &= (lab != t)
                for i in range(lab.shape[0]):
                    mi = mask[i]
                    if mi.any():
                        total += 1
                        correct += bool((pred[i][mi] == lab[i][mi]).all())
    finally:
        RecurrentMemoryCell.parallel_forward = orig_pf
    return correct / max(total, 1), total


def main():
    if not torch.cuda.is_available():
        print("CUDA required."); return
    tok = AutoTokenizer.from_pretrained(TOK)
    collate_fn = _load_collate(tok)
    model = _build_model()

    valid = datasets.load_from_disk(DATA)["valid"].select(range(N_EVAL))
    dl = DataLoader(valid, batch_size=BS, collate_fn=collate_fn)
    ignore_ids = set(tok.encode('!', add_special_tokens=False)
                     + tok.encode('|', add_special_tokens=False))

    em_norm, n = _em(model, dl, ignore_ids, zero_cache_pre_qt=False)
    print(f"\n[A] normal              EM = {em_norm:.4f}  (n={n})")
    em_zero, n = _em(model, dl, ignore_ids, zero_cache_pre_qt=True)
    print(f"[B] cache zeroed pre-QT EM = {em_zero:.4f}  (n={n})")

    print("\n--- verdict ---")
    if em_norm > 0.5 and em_zero < 0.05:
        print(f"EM collapses {em_norm:.3f} -> {em_zero:.3f} when the memory state is "
              f"wiped before QT.\nRetrieval is GENUINE — no answer bypass. The v6p1 "
              f"split is NOT needed for correctness.")
    elif em_zero >= 0.5:
        print(f"EM stays high ({em_zero:.3f}) with zero memory state — the answer "
              f"reaches QT WITHOUT the state. Real bypass; investigate the read path.")
    else:
        print(f"Inconclusive: normal EM {em_norm:.3f}, zeroed EM {em_zero:.3f}.")


if __name__ == "__main__":
    main()
