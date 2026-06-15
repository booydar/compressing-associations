"""Eval-only port of run_rmm_on_kv_retrieval-v5p4.py.

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

# Ensure repo root (one dir above eval/) is importable for modeling_rmt etc.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np
import torch
from torch.nn.utils.rnn import pad_sequence
import datasets

import accelerate
import transformers
from transformers import (
    AutoConfig, AutoTokenizer,
    Trainer, TrainingArguments,
    HfArgumentParser,
)

os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")


def split_token_ids_into_segments(token_ids, tokens_per_segment=None):
    if tokens_per_segment is None or tokens_per_segment <= 0:
        return [token_ids]
    return [token_ids[i:i + tokens_per_segment]
            for i in range(0, len(token_ids), tokens_per_segment)]


# Module-level args/tokenizer mirror the training script so collate_fn can use them.
args = None       # type: ignore
tokenizer = None  # type: ignore


def collate_fn(batch):
    def encode(text):
        return tokenizer.encode(text, add_special_tokens=False)

    segments_batch = []
    for sample in batch:
        context = sample['context']
        query   = sample['query']
        target  = sample['target']

        query_ids  = encode(query)
        target_ids = encode(target)
        qt_ids     = query_ids + target_ids
        context_ids_full = encode(context)
        sep_id = encode('|')
        if len(sep_id) == 1 and context_ids_full and context_ids_full[-1] == sep_id[0]:
            context_ids_full = context_ids_full[:-1]
            qt_ids = sep_id + qt_ids
        context_chunks = split_token_ids_into_segments(
            context_ids_full, tokens_per_segment=args.tokens_per_segment
        )

        segments = []
        for chunk_ids in context_chunks:
            segments.append({
                'input_ids':      torch.tensor(chunk_ids, dtype=torch.long),
                'attention_mask': torch.ones(len(chunk_ids), dtype=torch.long),
                'labels':         torch.full((len(chunk_ids),), -100, dtype=torch.long),
                'labels_mask':    torch.zeros(len(chunk_ids), dtype=torch.bool),
            })

        qt_input_ids = torch.tensor(qt_ids, dtype=torch.long)
        qt_attention_mask = torch.ones(len(qt_ids), dtype=torch.long)
        labels = torch.full((len(qt_ids),), -100, dtype=torch.long)
        if len(target_ids) > 0:
            labels[-len(target_ids):] = torch.tensor(target_ids, dtype=torch.long)
            labels_mask = torch.zeros(len(qt_ids), dtype=torch.bool)
            labels_mask[-len(target_ids) - 1:] = True
        else:
            labels_mask = torch.zeros(len(qt_ids), dtype=torch.bool)
        segments.append({
            'input_ids':      qt_input_ids,
            'attention_mask': qt_attention_mask,
            'labels':         labels,
            'labels_mask':    labels_mask,
        })
        segments_batch.append(segments)

    max_segments_in_batch = max(len(s) for s in segments_batch)
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
    for s in segments_batch:
        while len(s) < max_segments_in_batch:
            s.insert(0, {
                'input_ids':      torch.tensor([pad_id], dtype=torch.long),
                'attention_mask': torch.zeros(1, dtype=torch.long),
                'labels':         torch.tensor([-100], dtype=torch.long),
                'labels_mask':    torch.zeros(1, dtype=torch.bool),
            })

    batch_segments = []
    for i in range(max_segments_in_batch):
        input_ids    = pad_sequence([s[i]['input_ids']    for s in segments_batch], batch_first=True, padding_value=pad_id)
        attention_mask = pad_sequence([s[i]['attention_mask'] for s in segments_batch], batch_first=True, padding_value=0)
        labels       = pad_sequence([s[i]['labels']       for s in segments_batch], batch_first=True, padding_value=-100)
        labels_mask  = pad_sequence([s[i]['labels_mask']  for s in segments_batch], batch_first=True, padding_value=False)
        batch_segments.append({
            'input_ids': input_ids, 'attention_mask': attention_mask,
            'labels': labels, 'labels_mask': labels_mask,
        })
    full_labels = torch.cat([s['labels'] for s in batch_segments], dim=1)
    return {"segments": batch_segments, "labels": full_labels}


def make_compute_metrics(ignore_token_ids, tokenizer, predictions_out=None):
    def fn(eval_pred):
        predictions, labels, inputs = eval_pred.predictions, eval_pred.label_ids, eval_pred.inputs
        logits = predictions
        if isinstance(logits, (list, tuple)):
            logits = logits[0]
        logits = logits[..., :-1, :]
        labels = labels[..., 1:]
        preds  = np.argmax(logits, axis=-1)

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
                pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
                for i in range(len(preds)):
                    if not np.any(mask[i]):
                        continue
                    m = mask[i]
                    inp = inputs[i].copy()
                    inp[inp == -100] = pad_id
                    lab = labels[i].copy()
                    lab[lab == -100] = pad_id
                    pred_str = tokenizer.decode(preds[i][m].tolist(), skip_special_tokens=True).replace(' ', '')
                    label_str = tokenizer.decode(lab[m].tolist(), skip_special_tokens=True).replace(' ', '')
                    input_str = tokenizer.decode(inp.tolist(), skip_special_tokens=True).replace(' ', '')
                    f.write(json.dumps({
                        "input": input_str,
                        "prediction": pred_str,
                        "label": label_str,
                        "exact_match": per_sample_em[i],
                    }) + "\n")

        for pred, label, inp in zip(preds[:3], labels[:3], inputs[:3]):
            m = (label != -100)
            inp[inp == -100] = 0
            label[label == -100] = 0
            print('i:', tokenizer.decode(inp, skip_special_tokens=True).replace(' ', ''))
            print('p:', tokenizer.decode(pred[m], skip_special_tokens=True).replace(' ', ''))
            print('t:', tokenizer.decode(label[m], skip_special_tokens=True).replace(' ', ''))
            print('-' * 50)

        return {"token_accuracy": token_accuracy, "exact_match": exact_match}
    return fn


def resolve_checkpoint(model_cpt):
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
    model_cpt: str = field()
    data_path: str = field()
    exp_path: str = field()
    predictions_out: Optional[str] = field(default=None)
    metrics_out: Optional[str] = field(default=None)
    per_device_batch_size: int = field(default=64)
    tokenizer_path: str = field(default='./tokenizers/kv_alphabet_62/')
    base_model: str = field(default='llama')
    n_layer: int = field(default=4)
    n_head: int = field(default=4)
    n_embd: int = field(default=128)
    # GDN / FLA backbone
    fla_layer: str = field(default='GatedDeltaNet')
    state_size: int = field(default=32)
    expand_v: float = field(default=2.0)
    conv_kernel: int = field(default=4)
    use_short_conv: bool = field(default=True)
    # v5 memory-path
    num_memory_vectors: int = field(default=1)
    write_mode: str = field(default='cross_attn')
    read_mode: str = field(default='cross_attn')
    write_value_dim: Optional[int] = field(default=None)
    num_memory_heads: int = field(default=1)
    use_parallel_prefill: bool = field(default=True)
    tokens_per_segment: Optional[int] = field(default=None)
    # collate options (defaults disable memory task)
    memory_task_freq: float = field(default=0.0)
    memory_task: Optional[str] = field(default=None)
    memory_key_size: int = field(default=4)
    memory_value_size: int = field(default=4)
    # data params
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

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)

    if args.base_model == 'gpt2':
        config = AutoConfig.from_pretrained('gpt2')
        config.n_layer = args.n_layer; config.n_head = args.n_head; config.n_embd = args.n_embd
    elif args.base_model == 'pythia':
        config = AutoConfig.from_pretrained('EleutherAI/pythia-160m')
        config.num_hidden_layers = args.n_layer
        config.num_attention_heads = args.n_head
        config.hidden_size = args.n_embd
        config.intermediate_size = args.n_embd * 4
    elif args.base_model == 'llama':
        config = AutoConfig.from_pretrained('NousResearch/Llama-3.2-1B')
        config.num_hidden_layers = args.n_layer
        config.num_attention_heads = args.n_head
        config.num_key_value_heads = args.n_head
        config.hidden_size = args.n_embd
        config.head_dim = args.n_embd // args.n_head
        config.intermediate_size = args.n_embd * 4
    else:
        raise ValueError(f'Unsupported base_model: {args.base_model}')

    config.torch_dtype = "float32"
    config.vocab_size = tokenizer.vocab_size
    config.pad_token_id = tokenizer.convert_tokens_to_ids('[PAD]')
    config.bos_token_id = tokenizer.convert_tokens_to_ids('[BOS]')
    config.eos_token_id = tokenizer.convert_tokens_to_ids('[EOS]')

    from modeling_rmt.huggingface_rmm_v5p4 import RecurrentMemoryBase, RecurrentMemoryConfig

    head_dim = args.state_size // args.n_head

    rmm_config = RecurrentMemoryConfig(
        base_model_config  = config,
        fla_layer_name     = args.fla_layer,
        num_heads          = args.n_head,
        head_dim           = head_dim,
        expand_v           = args.expand_v,
        conv_size          = args.conv_kernel,
        use_short_conv     = args.use_short_conv,
        num_memory_vectors = args.num_memory_vectors,
        write_mode         = args.write_mode,
        read_mode          = args.read_mode,
        write_value_dim    = args.write_value_dim,
        num_memory_heads   = args.num_memory_heads,
        use_parallel_prefill = args.use_parallel_prefill,
        max_n_segments     = 10,
        think_token_id     = tokenizer.convert_tokens_to_ids('[THINK]'),
        answer_token_id    = tokenizer.convert_tokens_to_ids('[ANSWER]'),
        bos_token_id       = tokenizer.convert_tokens_to_ids('[BOS]'),
        eos_token_id       = tokenizer.convert_tokens_to_ids('[EOS]'),
    )
    model = RecurrentMemoryBase(rmm_config)
    model.main_input_name = 'labels'

    cpt_file, use_safetensors = resolve_checkpoint(args.model_cpt)
    if use_safetensors:
        from safetensors.torch import load_file
        sd = load_file(cpt_file)
    else:
        sd = torch.load(cpt_file, map_location='cpu')
    # HF Trainer sometimes wraps non-PreTrainedModel state with a "model." prefix.
    for prefix in ("module.", "model."):
        if sd and all(k.startswith(prefix) for k in sd):
            sd = {k[len(prefix):]: v for k, v in sd.items()}
            logger.info(f"  stripped state_dict prefix: {prefix!r}")
            break
    missing, unexpected = model.load_state_dict(sd, strict=False)
    # Llama (and most HF causal LMs) tie lm_head.weight ↔ embed_tokens.weight,
    # so safetensors saves only one of them. Re-tie and drop tied keys from
    # the "missing" list — they aren't really missing.
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
        data_collator=collate_fn,
        compute_metrics=compute_metrics,
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
