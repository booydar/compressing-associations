"""RMM v6p0 on bAbI (babilong qaX_0k).

RMM analog of test-time/example-scripts/babi/run_rmt_on_babi.sh, which runs
run_rmt_on_kv_retrieval.py on the babilong context/query/target data with a small
from-config gpt2 base (--base_model gpt2). Same 2-segment mapping as the squad
runner: segments = [context_seg, qt_seg].

Only the data loading differs from run_rmm_on_squad-v6p0.py: babilong is loaded
from disk (datasets.load_from_disk) with split-name normalization.
"""
import json
import logging
import os
from pathlib import Path

import torch
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass, field
import datasets

import accelerate
import transformers
from transformers import (
    AutoConfig, AutoTokenizer,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback, TrainerCallback,
    HfArgumentParser
)


os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")


def collate_fn(batch):
    """context/query/target -> RMM 2-segment list [context_seg, qt_seg].

    Identical to run_rmm_on_squad-v6p0.py: tokenize context and query+target,
    find target tokens via offset-mapping, emit RMM segment dicts with a
    labels_mask aligned to RMM's predict-next shift (position p in the loss iff
    p+1 is a target token).
    """
    context = [item['context'].strip() for item in batch]
    qt = [item['query'] + item['target'] for item in batch]

    ctx_enc = tokenizer(context, return_tensors="pt", add_special_tokens=True,
                        padding=True, pad_to_multiple_of=8,
                        max_length=args.max_context_length,
                        truncation=args.max_context_length is not None)
    context_input_ids = ctx_enc['input_ids']
    context_attention_mask = ctx_enc['attention_mask']

    qt_enc = tokenizer(qt, return_tensors="pt", add_special_tokens=True,
                       padding=True, pad_to_multiple_of=8, return_offsets_mapping=True)
    qt_input_ids = qt_enc['input_ids']
    qt_attention_mask = qt_enc['attention_mask']
    offsets_mapping = qt_enc['offset_mapping']

    tgt = torch.zeros_like(qt_input_ids, dtype=torch.bool)
    for i, item in enumerate(batch):
        query_seq_len = len(item['query'])
        target_seq_len = len(item['target'])
        target_st, target_end = query_seq_len, query_seq_len + target_seq_len
        in_target = False
        for j in range(len(offsets_mapping[i]) - 1, -1, -1):
            st, end = offsets_mapping[i][j]
            if st < target_end and end > target_st:
                tgt[i, j] = True
                in_target = True
            elif in_target:
                break

    qt_labels = torch.where(tgt, qt_input_ids, torch.full_like(qt_input_ids, -100))
    qt_labels_mask = torch.zeros_like(qt_input_ids, dtype=torch.bool)
    qt_labels_mask[:, :-1] = tgt[:, 1:]

    context_labels = torch.full_like(context_input_ids, -100)
    context_labels_mask = torch.zeros_like(context_input_ids, dtype=torch.bool)

    segments = [
        {
            'input_ids': context_input_ids,
            'attention_mask': context_attention_mask,
            'labels': context_labels,
            'labels_mask': context_labels_mask,
        },
        {
            'input_ids': qt_input_ids,
            'attention_mask': qt_attention_mask,
            'labels': qt_labels,
            'labels_mask': qt_labels_mask,
        },
    ]
    full_labels = torch.cat([context_labels, qt_labels], dim=1)
    return {"segments": segments, "labels": full_labels}


def preprocess_logits_for_metrics(logits, labels):
    return logits.argmax(dim=-1)


def compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer):
    preds, labels, inputs = eval_pred.predictions, eval_pred.label_ids, eval_pred.inputs
    preds = preds[..., :-1]
    labels = labels[..., 1:]

    mask = (labels != -100)
    for t_id in ignore_token_ids:
        mask &= (labels != t_id)

    accuracy = (preds[mask] == labels[mask]).mean()

    exact_match = np.mean([
        np.all(pred[mask[i]] == lab[mask[i]])
        for i, (pred, lab) in enumerate(zip(preds, labels))
        if np.any(mask[i])
    ]) if np.any(mask) else float('nan')

    n_samples = 5
    for pred, label, inp in zip(preds[:n_samples], labels[:n_samples], inputs[:n_samples]):
        m = (label != -100)
        inp = inp.copy()
        inp[inp == -100] = tokenizer.pad_token_id
        label = label.copy()
        label[label == -100] = tokenizer.pad_token_id
        print('i:', tokenizer.decode(inp, skip_special_tokens=True).strip())
        print('p:', tokenizer.decode(pred[m], skip_special_tokens=True).strip())
        print('t:', tokenizer.decode(label[m], skip_special_tokens=True).strip())
        print('-' * 50)

    return {
        "token_accuracy": float(accuracy),
        "exact_match": float(exact_match),
    }


class StopOnMetricValue(TrainerCallback):
    def __init__(self, metric_name, value, higher_is_better=True):
        self.metric_name      = metric_name
        self.value            = value
        self.higher_is_better = higher_is_better

    def on_evaluate(self, args, state, control, metrics, **kwargs):
        metric_to_check = self.metric_name if self.metric_name.startswith("eval_") else f"eval_{self.metric_name}"
        metric_value = metrics.get(metric_to_check)
        if metric_value is None:
            return
        op = np.greater_equal if self.higher_is_better else np.less_equal
        if op(metric_value, self.value):
            control.should_training_stop = True
            logger.info(f'metric {self.metric_name}={metric_value:.4f} >= {self.value:.4f}, stopping training.')


class CustomTrainer(Trainer):
    def create_scheduler(self, num_training_steps, optimizer=None):
        num_training_steps = int(num_training_steps / 0.9)
        return super().create_scheduler(num_training_steps, optimizer)

    def log(self, logs: Dict[str, float], start_time: Optional[float] = None) -> None:
        for cb in self.callback_handler.callbacks:
            if isinstance(cb, EarlyStoppingCallback):
                logs['patience'] = cb.early_stopping_patience_counter
                break
        return super().log(logs, start_time)


@dataclass
class ExperimentArgs:
    exp_path:                 str            = field()
    per_device_batch_size:    int            = field()
    data_path:                str            = field(default='./data/babilong_qa1_0k')
    tokenizer_path:           str            = field(default='gpt2')
    gradient_accumulation_steps: Optional[int]   = field(default=1)
    total_batch_size:         Optional[int]  = field(default=None)
    metric_for_best_model:    Optional[str]  = field(default='token_accuracy')
    warmup_steps:             Optional[int]  = field(default=1000)
    max_steps:                Optional[int]  = field(default=50000)
    logging_steps:            Optional[int]  = field(default=100)
    eval_steps:               Optional[int]  = field(default=100)
    weight_decay:             Optional[float]= field(default=0.0)
    learning_rate:            Optional[float]= field(default=1e-04)
    adam_beta1:               Optional[float]= field(default=0.9)
    adam_beta2:               Optional[float]= field(default=0.999)
    adam_epsilon:             Optional[float]= field(default=1e-8)
    lr_scheduler_type:        Optional[str]  = field(default='constant_with_warmup')
    early_stopping_patience:  Optional[int]  = field(default=50)
    seed:                     Optional[int]  = field(default=142)
    # base model: babi uses a small from-config gpt2 (--base_model gpt2), matching
    # run_rmt_on_babi.sh; --pretrained_model also supported.
    base_model:               Optional[str]  = field(default='gpt2')
    pretrained_model:         Optional[str]  = field(default=None)
    n_layer:                  Optional[int]  = field(default=4)
    n_head:                   Optional[int]  = field(default=1)
    n_embd:                   Optional[int]  = field(default=128)
    max_context_length:       Optional[int]  = field(default=None)
    # GDN / FLA parameters
    fla_layer:                Optional[str]  = field(default='GatedDeltaNet')
    state_size:               Optional[int]  = field(default=32)
    expand_v:                 Optional[float]= field(default=2.0)
    conv_kernel:              Optional[int]  = field(default=4)
    use_short_conv:           Optional[bool] = field(default=True)
    # v6 memory-path parameters
    num_memory_vectors:       Optional[int]  = field(default=8)
    write_mode:               Optional[str]  = field(default='cross_attn')
    read_mode:                Optional[str]  = field(default='cross_attn')
    write_value_dim:          Optional[int]  = field(default=None)
    num_memory_heads:         Optional[int]  = field(default=1)
    num_compress_heads:       Optional[int]  = field(default=None)   # compress/decompress CA heads (separate from GDN num_heads)
    thread_memory:            Optional[bool] = field(default=True)   # v6p4 cross-layer query threading
    use_parallel_prefill:     Optional[bool] = field(default=True)
    model_cpt:                Optional[str]  = field(default=None)


def build_rmm_model(args, tokenizer):
    from modeling_rmt.huggingface_rmm_v6p5 import RecurrentMemoryBase, RecurrentMemoryConfig

    base_config = None
    from_pretrained = None
    if args.pretrained_model is not None:
        from_pretrained = args.pretrained_model
    else:
        if args.base_model == 'gpt2':
            base_config = AutoConfig.from_pretrained('gpt2')
            base_config.n_layer = args.n_layer
            base_config.n_head  = args.n_head
            base_config.n_embd  = args.n_embd
        elif args.base_model == 'pythia':
            base_config = AutoConfig.from_pretrained('EleutherAI/pythia-160m')
            base_config.num_hidden_layers   = args.n_layer
            base_config.num_attention_heads = args.n_head
            base_config.hidden_size         = args.n_embd
            base_config.intermediate_size   = args.n_embd * 4
        elif args.base_model == 'llama':
            base_config = AutoConfig.from_pretrained('NousResearch/Llama-3.2-1B')
            base_config.num_hidden_layers   = args.n_layer
            base_config.num_attention_heads = args.n_head
            base_config.num_key_value_heads = args.n_head
            base_config.hidden_size         = args.n_embd
            base_config.head_dim            = args.n_embd // args.n_head
            base_config.intermediate_size   = args.n_embd * 4
        else:
            raise ValueError(f'Unsupported base_model: {args.base_model}')
        base_config.torch_dtype  = "float32"
        base_config.vocab_size   = tokenizer.vocab_size
        base_config.pad_token_id = tokenizer.pad_token_id
        base_config.bos_token_id = tokenizer.bos_token_id
        base_config.eos_token_id = tokenizer.eos_token_id
        base_config.use_cache    = False

    head_dim = args.state_size // args.n_head
    rmm_config = RecurrentMemoryConfig(
        base_model_config  = base_config,
        from_pretrained    = from_pretrained,
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
        num_compress_heads = args.num_compress_heads,
        use_parallel_prefill = args.use_parallel_prefill,
        thread_memory      = args.thread_memory,
        max_n_segments     = 10,
        think_token_id     = None,
        answer_token_id    = None,
        bos_token_id       = tokenizer.bos_token_id,
        eos_token_id       = tokenizer.eos_token_id,
    )
    model = RecurrentMemoryBase(rmm_config)
    model.main_input_name = 'labels'
    return model


def _normalize_splits(dataset):
    """babilong save_to_disk keeps the source split names; map to train/valid."""
    if 'valid' in dataset:
        valid_key = 'valid'
    elif 'validation' in dataset:
        valid_key = 'validation'
    elif 'test' in dataset:
        valid_key = 'test'
    else:
        raise KeyError(f'no validation split found in {list(dataset.keys())}')
    return datasets.DatasetDict({'train': dataset['train'], 'valid': dataset[valid_key]})


if __name__ == '__main__':
    parser = HfArgumentParser(ExperimentArgs)
    args = parser.parse_args_into_dataclasses()[0]

    accel = accelerate.Accelerator()
    from accelerate.logging import get_logger
    logger = get_logger('')
    transformers.utils.logging.set_verbosity(log_lvl)

    logger.info(f'num processes: {accel.num_processes}')
    logger.info(f'mixed precision: {accel.mixed_precision}')

    if args.pretrained_model is not None:
        args.base_model = None  # --pretrained_model overrides the default base_model='gpt2'

    if accel.is_main_process:
        Path(args.exp_path).mkdir(parents=True, exist_ok=True)
        json.dump({'cli_args': dict(vars(args))},
                  open(os.path.join(args.exp_path, 'config.json'), 'w'), indent=4)

    tok_path = args.pretrained_model or args.tokenizer_path
    tokenizer = AutoTokenizer.from_pretrained(tok_path)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    model = build_rmm_model(args, tokenizer)

    if args.model_cpt and args.model_cpt != 'None':
        model.load_state_dict(torch.load(args.model_cpt, map_location='cpu'), strict=False)
        print(f"Loaded checkpoint: {args.model_cpt}")

    logger.info(f"parameters: {sum(p.numel() for p in model.parameters()):,}")

    dataset = _normalize_splits(datasets.load_from_disk(args.data_path))

    ignore_token_ids = []

    def compute_metrics(eval_pred):
        return compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer)

    if args.total_batch_size is None:
        args.total_batch_size = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
    else:
        assert args.total_batch_size == args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps

    training_args = TrainingArguments(
        output_dir  = str(args.exp_path),
        logging_dir = str(args.exp_path),
        max_steps   = args.max_steps,
        per_device_train_batch_size = args.per_device_batch_size,
        per_device_eval_batch_size  = args.per_device_batch_size,
        gradient_accumulation_steps = args.gradient_accumulation_steps,
        warmup_steps        = args.warmup_steps,
        weight_decay        = args.weight_decay,
        learning_rate       = args.learning_rate,
        adam_beta1          = args.adam_beta1,
        adam_beta2          = args.adam_beta2,
        adam_epsilon        = args.adam_epsilon,
        lr_scheduler_type   = args.lr_scheduler_type,
        eval_strategy       = 'steps',
        save_strategy       = 'steps',
        save_steps          = args.eval_steps,
        eval_steps          = args.eval_steps,
        logging_steps       = args.logging_steps,
        report_to           = 'tensorboard',
        metric_for_best_model   = args.metric_for_best_model,
        load_best_model_at_end  = True,
        eval_on_start           = True,
        greater_is_better       = True,
        remove_unused_columns   = False,
        include_num_input_tokens_seen = False,
        include_for_metrics     = ['inputs'],
        save_total_limit        = 1,
        dataloader_num_workers  = 4,
        dataloader_pin_memory   = True,
        seed                    = args.seed,
    )

    trainer = CustomTrainer(
        model           = model,
        args            = training_args,
        train_dataset   = dataset['train'],
        eval_dataset    = dataset['valid'],
        data_collator   = collate_fn,
        compute_metrics = compute_metrics,
        preprocess_logits_for_metrics = preprocess_logits_for_metrics,
        callbacks=[
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience),
            StopOnMetricValue('exact_match', 1.0, higher_is_better=True),
        ],
    )
    trainer.train()
    logger.info('training done. running final evaluation...')
    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f'{metrics}')
    trainer.save_metrics(split='all', metrics=metrics)
