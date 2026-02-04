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

def collate_fn(batch):
    """
    Collate function for LM tasks, following the format of the KV retrieval collate_fn:
    - Each sample is a single segment (input_ids)
    - Pads input_ids, attention_mask, labels, and labels_mask across the batch
    - Applies loss masking according to args
    """
    from torch.nn.utils.rnn import pad_sequence
    import torch

    # Helper to get args if available
    global args

    # Prepare segment for each sample
    segments_batch = []
    for sample in batch:
        input_ids = torch.tensor(sample['input_ids'], dtype=torch.long)
        attention_mask = torch.ones(len(input_ids), dtype=torch.long)
        labels = input_ids.clone()
        labels_mask = torch.ones(len(input_ids), dtype=torch.bool)

        # Apply loss masking if specified in args
        if getattr(args, 'loss_from_last_seg_only', False):
            labels_mask[:-args.segment_size] = False
        if getattr(args, 'no_loss_from_first_segment', False):
            labels_mask[:args.segment_size] = False

        # For masked tokens, set label to -100
        labels[~labels_mask] = -100

        seg = {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'labels': labels,
            'labels_mask': labels_mask
        }
        segments_batch.append(seg)

    # Pad segments across the batch
    input_ids = pad_sequence([s['input_ids'] for s in segments_batch], batch_first=True, padding_value=0)
    attention_mask = pad_sequence([s['attention_mask'] for s in segments_batch], batch_first=True, padding_value=0)
    labels = pad_sequence([s['labels'] for s in segments_batch], batch_first=True, padding_value=-100)
    labels_mask = pad_sequence([s['labels_mask'] for s in segments_batch], batch_first=True, padding_value=False)
    print(f"[collate_fn] labels: {labels.shape}, {labels_mask.shape}")
    print(f"[collate_fn] input_ids: {input_ids.shape}, {attention_mask.shape}")
    # print(f"[collate_fn] attention_mask: {attention_mask.shape}")

    # Split to segments by args.segment_size
    input_ids = torch.chunk(input_ids, args.segment_size, dim=1)
    attention_mask = torch.chunk(attention_mask, args.segment_size, dim=1)
    # labels = torch.chunk(labels, args.segment_size, dim=1)
    labels_mask = torch.chunk(labels_mask, args.segment_size, dim=1)

    batch_segments = []
    for inp, att, lab_mask in zip(input_ids, attention_mask, labels_mask):
        batch_segment = {
            'input_ids': inp,
            'attention_mask': att,
            'labels': inp,
            'labels_mask': lab_mask
        }
        batch_segments.append(batch_segment)

    print(f"[collate_fn] segments: {len(batch_segments)}")
    print(f"[collate_fn] labels: {labels.shape}, {batch_segments[0]['labels'].shape}, {batch_segments[1]['labels'].shape}")
    print(f"[collate_fn] labels_mask: {batch_segments[0]['labels_mask'].shape}, {batch_segments[1]['labels_mask'].shape}")
    print(f"[collate_fn] input_ids: {batch_segments[0]['input_ids'].shape}, {batch_segments[1]['input_ids'].shape}")
    print(f"[collate_fn] attention_mask: {batch_segments[0]['attention_mask'].shape}, {batch_segments[1]['attention_mask'].shape}")
    print(f"[collate_fn] labels_values: {[c[m] for c, m in zip(batch_segments[0]['input_ids'], batch_segments[0]['labels_mask'])]}, \n\n\, {[c[m] for c, m in zip(batch_segments[1]['input_ids'], batch_segments[1]['labels_mask'])]}")
    1/0
    return {"segments": batch_segments, "labels": labels}

os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")


class StopOnMetricValue(TrainerCallback):
    def __init__(self, metric_name: str, value: float, higher_is_better: bool = True):
        self.metric_name = metric_name
        self.value = value
        self.higher_is_better = higher_is_better

    def on_evaluate(self, args, state, control, metrics, **kwargs):
        if not self.metric_name.startswith("eval_"):
            metric_to_check = f"eval_{self.metric_name}"
        metric_value = metrics.get(metric_to_check)
        if metric_value is None:
            return
        operator = np.greater_equal if self.higher_is_better else np.less_equal
        if operator(metric_value, self.value):
            control.should_training_stop = True
            logger.info(f'metric {self.metric_name}={metric_value:.4f} >= {self.value:.4f}, stopping training..')


class CustomTrainer(Trainer):
    def create_scheduler(self, num_training_steps: int, optimizer: torch.optim.Optimizer = None):
        num_training_steps = int(num_training_steps / 0.9)  # to make final lr not zero, for linear it is lr/10.
        return super().create_scheduler(num_training_steps, optimizer)

    def log(self, logs: Dict[str, float], start_time: Optional[float] = None) -> None:
        # log early stopping patience
        for cb in self.callback_handler.callbacks:
            if isinstance(cb, EarlyStoppingCallback):
                logs['patience'] = cb.early_stopping_patience_counter
                break
        return super().log(logs, start_time=start_time)


@dataclass
class ExperimentArgs:
    exp_path: str = field()
    task_name: str = field()
    per_device_batch_size: int = field()
    data_path: str = field(
        default='./data/N2-K4V4-S4(32-64)_1M',
    )
    tokenizer_path: str = field(
        default='./tokenizers/kv_alphabet_62/',
    )
    gradient_accumulation_steps: Optional[int] = field(default=1)
    total_batch_size: Optional[int] = field(default=None)
    metric_for_best_model: Optional[str] = field(default='token_accuracy')
    warmup_steps: Optional[int] = field(default=1000)
    max_steps: Optional[int] = field(default=50000)
    logging_steps: Optional[int] = field(default=100)
    eval_steps: Optional[int] = field(default=100)
    weight_decay: Optional[float] = field(default=0.0)
    learning_rate: Optional[float] = field(default=1e-04)
    lr_scheduler_type: Optional[str] = field(default='constant_with_warmup')
    early_stopping_patience: Optional[int] = field(default=50)
    seed: Optional[int] = field(default=142)
    base_model: Optional[str] = field(default='gpt2')
    from_pretrained: Optional[str] = field(default=None)
    tokenizer: Optional[str] = field(default=None)
    n_layer: Optional[int] = field(default=4)
    n_head: Optional[int] = field(default=4)
    n_embd: Optional[int] = field(default=128)
    # RMT parameters
    n_mem_tokens: Optional[int] = field(default=8)
    n_ctrl_tokens: Optional[int] = field(default=0)
    use_mem_proj: Optional[bool] = field(default=False)
    mem_proj_mode: Optional[str] = field(default="none")
    rmt_model: Optional[str] = field(default='rmt')
    segment_size: Optional[int] = field(default=1024)
    sample_size: Optional[int] = field(default=1024)
    val_sample_size: Optional[int] = field(default=1024)
    max_n_segments: Optional[int] = field(default=10)
    save_total_limit: Optional[int] = field(default=3)
    bf16: Optional[bool] = field(default=False)

if __name__ == '__main__':
    parser = HfArgumentParser(ExperimentArgs)
    args = parser.parse_args_into_dataclasses()[0]

    accel = accelerate.Accelerator()
    from accelerate.logging import get_logger
    logger = get_logger('')
    transformers.utils.logging.set_verbosity(log_lvl)

    logger.info(f'num processes: {accel.num_processes}')
    logger.info(f'mixed precision: {accel.mixed_precision}')
    logger.info(f'accelerator state: {accel.state}')

    if accel.is_main_process:
        config = {
            'cli_args': dict(vars(args)),
        }
        logger.info(f'saving experiment configuration to {args.exp_path}')
        Path(args.exp_path).mkdir(parents=True, exist_ok=True)
        json.dump(config, open(os.path.join(args.exp_path, 'config.json'), 'w'), indent=4)

    # create tokenizer

    # create model config
    if not args.from_pretrained:
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
        if args.base_model == 'gpt2':
            config = AutoConfig.from_pretrained('gpt2')
            config.n_layer = args.n_layer
            config.n_head = args.n_head
            config.n_embd = args.n_embd
        elif args.base_model == 'pythia':
            config = AutoConfig.from_pretrained('EleutherAI/pythia-160m')
            config.num_hidden_layers = args.n_layer
            config.num_attention_heads = args.n_head
            config.hidden_size = args.n_embd
            config.intermediate_size = config.hidden_size * 4
        elif args.base_model == 'llama':
            config = AutoConfig.from_pretrained('NousResearch/Llama-3.2-1B')
            config.num_hidden_layers = args.n_layer
            config.num_attention_heads = args.n_head
            config.num_key_value_heads = args.n_head
            config.hidden_size = args.n_embd
            config.head_dim = config.hidden_size // config.num_attention_heads
            config.intermediate_size = config.hidden_size * 4
        else:
            raise ValueError(f'Unsupported base model: {args.base_model}')

        config.torch_dtype = "float32"  # weights in float32, at training precision is controlled by accelerate
        config.vocab_size = tokenizer.vocab_size
        config.pad_token_id = tokenizer.convert_tokens_to_ids('[PAD]')
        config.bos_token_id = tokenizer.convert_tokens_to_ids('[BOS]')
        config.eos_token_id = tokenizer.convert_tokens_to_ids('[EOS]')
    else:
        tokenizer = AutoTokenizer.from_pretrained(args.from_pretrained)

    if args.rmt_model == 'rmt':
        from modeling_rmt.huggingface import RMTForReasoning, RMTConfig

        rmt_config = RMTConfig()
        if args.from_pretrained:
            rmt_config.from_pretrained = args.from_pretrained
            logger.info(f'Loading base model from pretrained: {args.from_pretrained}')
        else:
            rmt_config.base_model_config = config
            logger.info(f'Loading base model from config: {config}')
        rmt_config.num_mem_tokens = args.n_mem_tokens
        rmt_config.max_n_segments = args.max_n_segments

        model = RMTForReasoning(rmt_config)
        logger.info(f'Loaded RMTmodel: {model}')
    elif args.rmt_model == 'armt':
        from modeling_armt.huggingface import ARMTForCausalLMv2, ARMTConfig

        rmt_config = ARMTConfig()
        if args.from_pretrained:
            rmt_config.base_model_name = args.from_pretrained
            logger.info(f'Loading base model from pretrained: {args.from_pretrained}')
        else:
            rmt_config.base_model_config = config
            logger.info(f'Loading base model from config: {config}')
        rmt_config.num_mem_tokens = args.n_mem_tokens
        rmt_config.max_n_segments = args.max_n_segments

        model = ARMTForCausalLMv2(rmt_config)
        logger.info(f'Loaded ARMT model: {model}')
    else:
        raise ValueError(f'Unsupported RMT model: {args.rmt_model}')


    model.main_input_name = 'labels'

    logger.info(f'model config: {model.config}')
    logger.info(f'model: {model}')

    # if args.tokenizer:
    #     tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    # elif args.base_model:
    #     tokenizer = AutoTokenizer.from_pretrained(args.from_pretrained)
    # else:
    #     tokenizer = AutoTokenizer.from_pretrained(args.model_cfg)

    # Prepare datasets
    logger.info(f'preparing dataset for {args.task_name}')

    segment_size = args.segment_size
    history_size = args.sample_size - segment_size

    if args.val_sample_size is not None:
        val_history_size = args.val_sample_size - segment_size
    else:
        val_history_size = history_size

    def group_texts(examples, segment_size, history_size=None):
        concatenated_examples = {k: list(chain(*examples[k])) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])

        if history_size is None:
            result = {
                k: [t[i: i + segment_size] for i in range(0, total_length, segment_size)]
                for k, t in concatenated_examples.items()
            }
        else:
            result = {
                k: [t[max({0, i - history_size}): i + segment_size]
                    for i in range(history_size, total_length, segment_size)]
                for k, t in concatenated_examples.items()
            }
        return result

    id_pad_value = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id

    with accel.main_process_first():
        if args.task_name is not None:
            if 'fineweb' in args.task_name:
                dataset = datasets.load_dataset("HuggingFaceFW/fineweb-edu", 
                                                      name="sample-10BT",
                                                      cache_dir="/workspace-SR006.nfs2/bulatov/.cache/huggingface/datasets/HuggingFaceFW___fineweb-edu/default-faeb9770c8ce8992",
                                                      streaming=False
                                                      )
                valid_dataset = dataset["train"].select(range(100))
                test_dataset = dataset["train"].select(range(100, 1100))
                train_dataset = dataset["train"].select(range(1100, len(dataset["train"])))
            else:
                raise NotImplementedError("")
            # train_dataset = train_dataset.map(lambda x: tokenizer(x['text'],
            #                                   add_special_tokens=False),
            #                                   batched=True,
            #                                   batch_size=10_000,
            #                                   num_proc=16,
            #                                   )
            # valid_dataset = valid_dataset.map(lambda x: tokenizer(x['text'],
            #                                   add_special_tokens=False),
            #                                   batched=True,
            #                                   batch_size=10_000,
            #                                   num_proc=16,
            #                                   )
            # test_dataset = test_dataset.map(lambda x: tokenizer(x['text'],
            #                                 add_special_tokens=False),
            #                                 batched=True,
            #                                 batch_size=10_000,
            #                                 num_proc=16,
            #                                 )
            # Define fast tokenizer function (drop unneeded outputs)
            def tok(batch):
                return tokenizer(
                    batch["text"],
                    add_special_tokens=False,
                    return_attention_mask=False,
                    return_token_type_ids=False,
                )

            # Tune these according to your machine
            BATCH_SIZE = 10_000     # increase if memory allows
            NUM_PROC = 32           # match your CPU cores

            # Tokenize and save datasets
            train_dataset = train_dataset.map(
                tok,
                batched=True,
                batch_size=BATCH_SIZE,
                num_proc=NUM_PROC,
            )
            valid_dataset = valid_dataset.map(
                tok,
                batched=True,
                batch_size=BATCH_SIZE,
                num_proc=NUM_PROC,
            )
            test_dataset = test_dataset.map(
                tok,
                batched=True,
                batch_size=BATCH_SIZE,
                num_proc=NUM_PROC,
            )
        else:
            raise NotImplementedError("")

    with accel.main_process_first():
        train_dataset = train_dataset.select_columns(['input_ids']).map(lambda x: group_texts(x, segment_size, history_size),
                                                                        batched=True,
                                                                        # batch_size=100_000 * 128 // segment_size,
                                                                        # desc=f"Grouping train in chunks of {segment_size} and history {history_size}"
                                                                        )
        valid_dataset = valid_dataset.select_columns(['input_ids']).map(lambda x: group_texts(x, segment_size, val_history_size),
                                                                        batched=True,
                                                                        # batch_size=100_000 * 128 // segment_size,
                                                                        # desc=f"Grouping valid in chunks of {segment_size} and history {val_history_size}"
                                                                        )
        test_dataset = test_dataset.select_columns(['input_ids']).map(lambda x: group_texts(x, segment_size, val_history_size),
                                                                      batched=True,
                                                                        # batch_size=100_000 * 128 // segment_size,
                                                                      #  desc=f"Grouping test in chunks of {segment_size} and history {val_history_size}"
                                                                      )

    num_valid_examples = 100
    valid_inds = np.linspace(1, len(valid_dataset)-1, num_valid_examples).astype(int).tolist()
    valid_dataset = valid_dataset.select(valid_inds)

    output_dir = Path(args.exp_path)

    if args.total_batch_size is None:
        args.total_batch_size = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
    else:
        args_total_bs = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
        assert args.total_batch_size == args_total_bs

    # Training arguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        logging_dir=output_dir,

        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_batch_size,
        per_device_eval_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        warmup_steps=args.warmup_steps,
        weight_decay=args.weight_decay,
        learning_rate=args.learning_rate,
        lr_scheduler_type=args.lr_scheduler_type,

        eval_strategy='steps',
        save_strategy='steps',
        save_steps=args.eval_steps,
        eval_steps=args.eval_steps,
        logging_steps=args.logging_steps,
        report_to='tensorboard',
        metric_for_best_model=args.metric_for_best_model,
        load_best_model_at_end=True,
        eval_on_start=True,
        greater_is_better=True,
        remove_unused_columns=False,
        include_num_input_tokens_seen=False,  # input_ids is a dict, so HF Trainer cant get number of tokens
        include_for_metrics=['inputs'],
        save_total_limit=args.save_total_limit,
        dataloader_num_workers=4,
        dataloader_pin_memory=True,
        bf16=args.bf16,
        seed=args.seed,
    )

    # Initialize Trainer
    trainer = CustomTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        data_collator=collate_fn,
        # compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience),
                   StopOnMetricValue(metric_name='exact_match', value=1.0, higher_is_better=True),
                   ],
    )
    # Train the model
    trainer.train()
    logger.info('training done. running final evaluation...')
    metrics = trainer.evaluate(valid_dataset)
    logger.info(f'{metrics}')
    trainer.save_metrics(split='all', metrics=metrics)
