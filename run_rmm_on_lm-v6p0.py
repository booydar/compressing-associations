"""RMM v6p0 on language modeling (wikitext-103).

RMM analog of test-time/example-scripts/run_rmt_on_lm.py. The wikitext pipeline
(tokenize -> group_texts into context_size+segment_size windows) is reused
verbatim; each window maps onto RMM's 2 segments exactly as RMT assigns them:

    context segment (memory) = window[context_size:]   (the later segment_size tokens)
    qt segment      (loss)   = window[:context_size]    (the earlier context_size tokens)

This preserves RMT's window-half assignment. NOTE this is the same (reversed vs.
plain next-token) ordering as run_rmt_on_lm.py: the *later* half is written to
memory and LM loss is computed on the *earlier* half. With the default
context_size == segment_size it is a symmetric memory-LM probe.

Windows are filtered to the exact full length (context_size+segment_size) so the
context segment is always non-empty and uniform (no padding, parallel-prefill OK).
"""
import json
import logging
import os
from pathlib import Path
from itertools import chain

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
from torch.nn.utils.rnn import pad_sequence


os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")


def collate_fn(batch):
    """LM windows -> RMM 2-segment list [context_seg (memory), qt_seg (loss)].

    Mirrors run_rmt_on_lm.py's context/query split. LM loss is over the qt
    segment (non-pad) tokens. labels_mask is built on the full concatenated
    sequence so position p is in the loss iff p+1 is a non-pad qt token (RMM's
    predict-next shift); this includes the context->qt boundary token.
    """
    pad_id = tokenizer.pad_token_id

    context_ids_list = []   # window[context_size:] -> memory
    query_ids_list = []     # window[:context_size] -> loss
    for sample in batch:
        input_ids = torch.tensor(sample['input_ids'], dtype=torch.long)
        context_ids_list.append(input_ids[args.context_size:])
        query_ids_list.append(input_ids[:args.context_size])

    ctx_lens = [len(x) for x in context_ids_list]
    q_lens = [len(x) for x in query_ids_list]

    context_input_ids = pad_sequence(context_ids_list, batch_first=True, padding_value=pad_id)
    query_input_ids = pad_sequence(query_ids_list, batch_first=True, padding_value=pad_id)
    C, Q = context_input_ids.size(1), query_input_ids.size(1)

    context_attention_mask = torch.zeros_like(context_input_ids)
    for i, l in enumerate(ctx_lens):
        context_attention_mask[i, :l] = 1
    query_attention_mask = torch.zeros_like(query_input_ids)
    for i, l in enumerate(q_lens):
        query_attention_mask[i, :l] = 1

    context_labels = torch.full_like(context_input_ids, -100)
    query_labels = torch.where(query_attention_mask.bool(), query_input_ids,
                               torch.full_like(query_input_ids, -100))

    full_labels = torch.cat([context_labels, query_labels], dim=1)
    full_mask = torch.zeros_like(full_labels, dtype=torch.bool)
    full_mask[:, :-1] = (full_labels[:, 1:] != -100)

    segments = [
        {
            'input_ids': context_input_ids,
            'attention_mask': context_attention_mask,
            'labels': context_labels,
            'labels_mask': full_mask[:, :C],
        },
        {
            'input_ids': query_input_ids,
            'attention_mask': query_attention_mask,
            'labels': query_labels,
            'labels_mask': full_mask[:, C:],
        },
    ]
    return {"segments": segments, "labels": full_labels}


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
    dataset_name:             str            = field(default='wikitext')
    tokenizer_path:           str            = field(default='gpt2')
    gradient_accumulation_steps: Optional[int]   = field(default=1)
    total_batch_size:         Optional[int]  = field(default=None)
    metric_for_best_model:    Optional[str]  = field(default='loss')
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
    base_model:               Optional[str]  = field(default=None)
    pretrained_model:         Optional[str]  = field(default=None)
    n_layer:                  Optional[int]  = field(default=4)
    n_head:                   Optional[int]  = field(default=1)
    n_embd:                   Optional[int]  = field(default=128)
    # GDN / FLA parameters
    fla_layer:                Optional[str]  = field(default='GatedDeltaNet')
    state_size:               Optional[int]  = field(default=32)
    expand_v:                 Optional[float]= field(default=2.0)
    conv_kernel:              Optional[int]  = field(default=4)
    use_short_conv:           Optional[bool] = field(default=True)
    # v6 memory-path parameters
    num_memory_vectors:       Optional[int]  = field(default=32)
    write_mode:               Optional[str]  = field(default='cross_attn')
    read_mode:                Optional[str]  = field(default='cross_attn')
    write_value_dim:          Optional[int]  = field(default=None)
    num_memory_heads:         Optional[int]  = field(default=1)
    use_parallel_prefill:     Optional[bool] = field(default=True)
    model_cpt:                Optional[str]  = field(default=None)
    # LM-specific parameters
    segment_size:             int            = field(default=128)
    context_size:             int            = field(default=128)
    validate_only:            Optional[bool] = field(default=False)
    num_proc:                 Optional[int]  = field(default=32)
    max_train_samples:        Optional[int]  = field(default=None)  # raw rows; for smoke
    max_eval_samples:         Optional[int]  = field(default=None)  # raw rows; for smoke


def build_rmm_model(args, tokenizer):
    from modeling_rmt.huggingface_rmm_v6p0 import RecurrentMemoryBase, RecurrentMemoryConfig

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
        use_parallel_prefill = args.use_parallel_prefill,
        max_n_segments     = 10,
        think_token_id     = None,
        answer_token_id    = None,
        bos_token_id       = tokenizer.bos_token_id,
        eos_token_id       = tokenizer.eos_token_id,
    )
    model = RecurrentMemoryBase(rmm_config)
    model.main_input_name = 'labels'
    return model


def group_texts(examples, seg_size, context_size):
    concatenated = {k: list(chain(*examples[k])) for k in examples.keys()}
    total_len = len(concatenated[list(examples.keys())[0]])
    result = {
        k: [t[max(0, i - context_size):i + seg_size]
            for i in range(context_size, total_len, seg_size)]
        for k, t in concatenated.items()
    }
    return result


if __name__ == '__main__':
    parser = HfArgumentParser(ExperimentArgs)
    args = parser.parse_args_into_dataclasses()[0]

    accel = accelerate.Accelerator()
    from accelerate.logging import get_logger
    logger = get_logger('')
    transformers.utils.logging.set_verbosity(log_lvl)

    logger.info(f'num processes: {accel.num_processes}')
    logger.info(f'mixed precision: {accel.mixed_precision}')

    assert not (args.pretrained_model is not None and args.base_model is not None), \
        "only one of --pretrained_model / --base_model must be set"

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

    segment_size = args.segment_size
    context_size = args.context_size
    full_len = context_size + segment_size
    logger.info(f"[dataset] segment_size={segment_size} context_size={context_size}")

    with accel.main_process_first():
        if 'wikitext' in args.dataset_name:
            raw_dataset = datasets.load_dataset("wikitext", name="wikitext-103-raw-v1", streaming=False)
            train_dataset = raw_dataset["train"]
            valid_dataset = raw_dataset["validation"]
            test_dataset = raw_dataset["test"]
        else:
            raise NotImplementedError(f"LM dataset {args.dataset_name} not implemented")

        if args.max_train_samples is not None:
            train_dataset = train_dataset.select(range(min(args.max_train_samples, len(train_dataset))))
        if args.max_eval_samples is not None:
            valid_dataset = valid_dataset.select(range(min(args.max_eval_samples, len(valid_dataset))))
            test_dataset = test_dataset.select(range(min(args.max_eval_samples, len(test_dataset))))

        def tok(batch):
            return tokenizer(batch["text"], add_special_tokens=False,
                             return_attention_mask=False, return_token_type_ids=False)

        def prep(ds):
            ds = ds.map(tok, batched=True, batch_size=10_000, num_proc=args.num_proc)
            ds = ds.select_columns(['input_ids']).map(
                lambda x: group_texts(x, segment_size, context_size), batched=True)
            # keep only full windows so the context segment is non-empty & uniform
            ds = ds.filter(lambda x: len(x['input_ids']) == full_len)
            return ds

        logger.info("[dataset] preparing train/valid/test...")
        train_dataset = prep(train_dataset)
        valid_dataset = prep(valid_dataset)
        test_dataset = prep(test_dataset)
    dataset = {'train': train_dataset, 'valid': valid_dataset, 'test': test_dataset}

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
        greater_is_better       = False,
        remove_unused_columns   = False,
        include_num_input_tokens_seen = False,
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
        compute_metrics = None,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience)],
    )

    if not args.validate_only:
        trainer.train()
        logger.info('training done. running final evaluation...')

    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f'valid: {metrics}')
    trainer.save_metrics(split='all', metrics=metrics)

    metrics_test = trainer.evaluate(dataset['test'])
    logger.info(f'test: {metrics_test}')
    trainer.save_metrics(split='test', metrics=metrics_test)
