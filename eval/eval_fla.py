"""Eval-only port of run_fla_on_kv_retrieval-default.py.

Same model/tokenizer build as the original training script, but:
  - never calls trainer.train(); always evaluates dataset['valid']
  - loads weights from --model_cpt (file OR run dir containing checkpoint-*)
  - dumps per-sample predictions JSONL to --predictions_out
  - dumps aggregate metrics JSON to --metrics_out
"""
import json
import logging
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np
import torch
import datasets

import accelerate
import transformers
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    Trainer,
    TrainingArguments,
    HfArgumentParser,
)

os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")

# Register native FLA models so AutoModelForCausalLM can find them
import fla.models.mamba          # noqa: F401
import fla.models.mamba2         # noqa: F401
import fla.models.gated_deltanet # noqa: F401
import fla.models.delta_net      # noqa: F401
import fla.models.gla            # noqa: F401
import fla.models.hgrn           # noqa: F401
import fla.models.hgrn2          # noqa: F401
import fla.models.rwkv6          # noqa: F401
import fla.models.rwkv7          # noqa: F401
import fla.models.retnet         # noqa: F401

from fla.models.mamba.configuration_mamba import MambaConfig
from fla.models.mamba2.configuration_mamba2 import Mamba2Config
from fla.models.gated_deltanet.configuration_gated_deltanet import GatedDeltaNetConfig
from fla.models.delta_net.configuration_delta_net import DeltaNetConfig
from fla.models.gla.configuration_gla import GLAConfig
from fla.models.hgrn.configuration_hgrn import HGRNConfig
from fla.models.hgrn2.configuration_hgrn2 import HGRN2Config
from fla.models.rwkv6.configuration_rwkv6 import RWKV6Config
from fla.models.rwkv7.configuration_rwkv7 import RWKV7Config
from fla.models.retnet.configuration_retnet import RetNetConfig

FLA_DEFAULT_CONFIGS = {
    "mamba":           MambaConfig,
    "mamba2":          Mamba2Config,
    "gated_delta_net": GatedDeltaNetConfig,
    "delta_net":       DeltaNetConfig,
    "gla":             GLAConfig,
    "hgrn":            HGRNConfig,
    "hgrn2":           HGRN2Config,
    "rwkv6":           RWKV6Config,
    "rwkv7":           RWKV7Config,
    "retention":       RetNetConfig,
}


def build_fla_config(base_model, args, tokenizer):
    common = dict(
        vocab_size=tokenizer.vocab_size,
        hidden_size=args.n_embd,
        num_hidden_layers=args.n_layer,
        pad_token_id=tokenizer.pad_token_id,
        use_cache=False,
        fuse_cross_entropy=False,
    )
    if base_model in ("mamba", "mamba2"):
        if args.state_size is not None:
            common["state_size"] = args.state_size
        if args.conv_kernel is not None:
            common["conv_kernel"] = args.conv_kernel
    elif base_model == "gated_delta_net":
        common["num_heads"] = args.n_head
        if args.state_size is not None and args.n_head:
            common["head_dim"] = args.state_size // args.n_head
        if args.conv_kernel is not None:
            common["conv_size"] = args.conv_kernel
    elif base_model in ("delta_net", "gla", "hgrn", "hgrn2", "rwkv6", "rwkv7", "retention"):
        common["num_heads"] = args.n_head
        if args.state_size is not None:
            common["state_size"] = args.state_size
        if args.conv_kernel is not None:
            common.setdefault("conv_kernel", args.conv_kernel)
    cfg_cls = FLA_DEFAULT_CONFIGS[base_model]
    return cfg_cls(**common)


def collate_fn(batch, tokenizer, max_input_length=None):
    seq = [item['context'] + item['query'] + item['target'] for item in batch]
    seq_encoded = tokenizer(
        seq, return_tensors="pt", add_special_tokens=True,
        padding=True, pad_to_multiple_of=8, max_length=max_input_length,
        truncation=True, return_offsets_mapping=True,
    )
    input_ids = seq_encoded['input_ids']
    offsets_mapping = seq_encoded['offset_mapping']
    attn_mask = (input_ids != tokenizer.pad_token_id).to(dtype=torch.long)
    labels_mask = torch.zeros_like(input_ids)
    for i, item in enumerate(batch):
        input_seq_len = len(item['context']) + len(item['query'])
        target_seq_len = len(item['target'])
        target_st, target_end = input_seq_len, input_seq_len + target_seq_len
        in_target = False
        for j in range(len(offsets_mapping[i]) - 1, -1, -1):
            st, end = offsets_mapping[i][j]
            if st < target_end and end > target_st:
                labels_mask[i, j] = 1
                in_target = True
            elif in_target:
                break
    labels = input_ids * labels_mask + (1 - labels_mask) * -100
    return {'input_ids': input_ids, 'attention_mask': attn_mask, 'labels': labels}


def preprocess_logits_for_metrics(logits, labels):
    return logits.argmax(dim=-1)


def make_compute_metrics(ignore_token_ids, tokenizer, predictions_out=None):
    def fn(eval_pred):
        preds = eval_pred.predictions[..., :-1]
        labels = eval_pred.label_ids[..., 1:]
        inputs = eval_pred.inputs

        mask = (labels != -100)
        for t_id in ignore_token_ids:
            mask &= (labels != t_id)

        token_accuracy = float((preds[mask] == labels[mask]).mean())

        per_sample_em = [
            bool(np.all(preds[i][mask[i]] == labels[i][mask[i]]))
            if np.any(mask[i]) else False
            for i in range(len(preds))
        ]
        n_with_targets = sum(1 for i in range(len(preds)) if np.any(mask[i]))
        exact_match = (
            float(np.mean([per_sample_em[i] for i in range(len(preds)) if np.any(mask[i])]))
            if n_with_targets > 0 else float('nan')
        )

        if predictions_out is not None:
            Path(predictions_out).parent.mkdir(parents=True, exist_ok=True)
            with open(predictions_out, "w") as f:
                pad_id = tokenizer.pad_token_id
                for i in range(len(preds)):
                    if not np.any(mask[i]):
                        continue
                    m = mask[i]
                    inp = inputs[i].copy()
                    inp[inp == -100] = pad_id
                    lab = labels[i].copy()
                    lab[lab == -100] = pad_id
                    pred_arr = preds[i]
                    pred_str = tokenizer.decode(pred_arr[m].tolist(), skip_special_tokens=True).replace(' ', '')
                    label_str = tokenizer.decode(lab[m].tolist(), skip_special_tokens=True).replace(' ', '')
                    input_str = tokenizer.decode(inp.tolist(), skip_special_tokens=True).replace(' ', '')
                    f.write(json.dumps({
                        "input": input_str,
                        "prediction": pred_str,
                        "label": label_str,
                        "exact_match": per_sample_em[i],
                    }) + "\n")

        # Print first few decoded predictions for visual sanity-check.
        for pred, label, inp in zip(preds[:3], labels[:3], inputs[:3]):
            m = (label != -100)
            inp[inp == -100] = tokenizer.pad_token_id
            label[label == -100] = tokenizer.pad_token_id
            print('i:', tokenizer.decode(inp, skip_special_tokens=True).strip())
            print('p:', tokenizer.decode(pred[m], skip_special_tokens=True).strip())
            print('t:', tokenizer.decode(label[m], skip_special_tokens=True).strip())
            print('-' * 50)

        return {"token_accuracy": token_accuracy, "exact_match": exact_match}
    return fn


def resolve_checkpoint(model_cpt):
    """Mirror ARMT/RMM loader logic: accept file or run-dir, prefer model_best,
    fall back to last checkpoint-* dir, prefer .bin over .safetensors."""
    if os.path.isfile(model_cpt):
        return model_cpt, model_cpt.endswith(".safetensors")
    if not os.path.isdir(model_cpt):
        raise FileNotFoundError(f"--model_cpt not found: {model_cpt}")
    dir_files = os.listdir(model_cpt)
    if "model_best" in dir_files:
        cand = os.path.join(model_cpt, "model_best", "pytorch_model.bin")
        if os.path.exists(cand): return cand, False
        cand_st = os.path.join(model_cpt, "model_best", "model.safetensors")
        if os.path.exists(cand_st): return cand_st, True
    checkpoints = sorted([d for d in dir_files if d.startswith("checkpoint-")])
    if not checkpoints:
        raise FileNotFoundError(f"No checkpoint-* directory in {model_cpt}")
    ckpt_dir = os.path.join(model_cpt, checkpoints[-1])
    cand = os.path.join(ckpt_dir, "pytorch_model.bin")
    if os.path.exists(cand): return cand, False
    cand_st = os.path.join(ckpt_dir, "model.safetensors")
    if os.path.exists(cand_st): return cand_st, True
    raise FileNotFoundError(f"No weights file in {ckpt_dir}")


@dataclass
class EvalArgs:
    model_cpt: str = field()  # path to checkpoint file or run dir
    data_path: str = field()
    exp_path: str = field()  # output dir (for HF Trainer scratch + logs)
    predictions_out: str = field(default=None)
    metrics_out: str = field(default=None)
    per_device_batch_size: int = field(default=64)
    tokenizer_path: str = field(default='./tokenizers/kv_alphabet_62/')
    # model config (must match training)
    base_model: str = field(default='gated_delta_net')
    n_layer: int = field(default=4)
    n_head: int = field(default=4)
    n_embd: int = field(default=128)
    state_size: Optional[int] = field(default=32)
    conv_kernel: Optional[int] = field(default=4)
    max_input_length: Optional[int] = field(default=None)
    attn_implementation: Optional[str] = field(default=None)
    # data params (only used if data has to be regenerated, which it shouldn't)
    n_pairs: Optional[int] = field(default=None)
    n_keys: Optional[int] = field(default=None)
    n_values: Optional[int] = field(default=None)
    seed: int = field(default=142)
    allow_load_mismatch: bool = field(default=False)


if __name__ == '__main__':
    args = HfArgumentParser(EvalArgs).parse_args_into_dataclasses()[0]

    accel = accelerate.Accelerator()
    transformers.utils.logging.set_verbosity(log_lvl)
    logger.info(f'mixed precision: {accel.mixed_precision}')

    dtype = {'bf16': torch.bfloat16, 'fp16': torch.float16}.get(accel.mixed_precision, torch.float32)

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    tokenizer.truncation_side = 'left'

    cfg = build_fla_config(args.base_model, args, tokenizer)
    model = AutoModelForCausalLM.from_config(cfg)
    model.config.use_cache = False

    cpt_file, use_safetensors = resolve_checkpoint(args.model_cpt)
    if use_safetensors:
        from safetensors.torch import load_file
        sd = load_file(cpt_file)
    else:
        sd = torch.load(cpt_file, map_location='cpu')
    for prefix in ("module.", "model."):
        if sd and all(k.startswith(prefix) for k in sd):
            sd = {k[len(prefix):]: v for k, v in sd.items()}
            logger.info(f"  stripped state_dict prefix: {prefix!r}")
            break
    missing, unexpected = model.load_state_dict(sd, strict=False)
    tied_keys = set()
    for sub in model.modules():
        if hasattr(sub, "tie_weights") and callable(getattr(sub, "tie_weights")):
            try: sub.tie_weights()
            except Exception: pass
        for k in getattr(sub, "_tied_weights_keys", []) or []:
            tied_keys.add(k)
    missing = [k for k in missing if not any(k.endswith(t) for t in tied_keys)]
    logger.info(f"Loaded checkpoint: {cpt_file}")
    logger.info(f"  state_dict: ckpt_keys={len(sd)} model_keys={len(list(model.state_dict()))}")
    logger.info(f"  tied_keys (excluded from missing): {sorted(tied_keys)}")
    logger.info(f"  missing   ({len(missing)}): {list(missing)[:10]}{' ...' if len(missing) > 10 else ''}")
    logger.info(f"  unexpected({len(unexpected)}): {list(unexpected)[:10]}{' ...' if len(unexpected) > 10 else ''}")
    if (missing or unexpected) and not args.allow_load_mismatch:
        raise RuntimeError(
            f"checkpoint/model key mismatch ({len(missing)} missing, "
            f"{len(unexpected)} unexpected). Pass --allow_load_mismatch True "
            f"to ignore (only after verifying the mismatch is intentional)."
        )
    logger.info(f"parameters: {sum(p.numel() for p in model.parameters()):,}")

    dataset = datasets.load_from_disk(args.data_path)

    def data_collator(batch):
        return collate_fn(batch, tokenizer, max_input_length=args.max_input_length)

    ignore_token_ids = [tokenizer.convert_tokens_to_ids(t) for t in ['!', '|']]
    compute_metrics = make_compute_metrics(ignore_token_ids, tokenizer,
                                           predictions_out=args.predictions_out)

    output_dir = Path(args.exp_path); output_dir.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        logging_dir=str(output_dir),
        per_device_eval_batch_size=args.per_device_batch_size,
        eval_strategy='no',
        save_strategy='no',
        report_to=[],
        remove_unused_columns=False,
        include_for_metrics=['inputs'],
        dataloader_num_workers=0,
        dataloader_pin_memory=True,
        seed=args.seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        eval_dataset=dataset['valid'],
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        preprocess_logits_for_metrics=preprocess_logits_for_metrics,
    )

    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f"eval metrics: {metrics}")

    metrics_out = args.metrics_out or os.path.join(str(output_dir), "metrics.json")
    Path(metrics_out).parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_out, "w") as f:
        json.dump({
            **{k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
               for k, v in metrics.items()},
            "_data_path": args.data_path,
            "_model_cpt": args.model_cpt,
            "_checkpoint_file": cpt_file,
        }, f, indent=2)
    logger.info(f"wrote metrics → {metrics_out}")
    if args.predictions_out:
        logger.info(f"wrote predictions → {args.predictions_out}")
