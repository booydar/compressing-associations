import json
import logging
import os
from pathlib import Path

import torch
from torch.nn.utils.rnn import pad_sequence

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

def split_context_into_segments(context, pairs_per_segment=None):
    if pairs_per_segment is None:
        return [context]
    clean_context = context[1:-2].strip()
    pairs = [f"!{p}!" for p in clean_context.split("!!")]

    segments = [pairs[i:i + pairs_per_segment] for i in range(0, len(pairs), pairs_per_segment)]
    segments = [''.join(s) for s in segments]
    return segments


def collate_fn(batch):
    """
    Collate function that splits each sample into two segments:
    - First segment: context
    - Second segment: query + target
    Pads segments across the batch to the same length.
    """
    def encode(text):
        return tokenizer.encode(text, add_special_tokens=False)

    segments_batch = []
    for idx, sample in enumerate(batch):
        context = sample['context']
        
        perform_memory_task = torch.rand(1) < args.memory_task_freq
        if perform_memory_task and args.memory_task == "reconstruct":
            query = '!?'
            target = '!?' + context[2:-2]
        elif perform_memory_task and args.memory_task == "continue":
            # print(f"[collate_fn] ", args.memory_key_size, args.memory_value_size, len(context))
            query_start_ind = torch.randint(0, len(context) - args.memory_key_size - args.memory_value_size - 4, (1,))
            query = '!?' + context[query_start_ind:query_start_ind + args.memory_key_size]
            target = '!?' + context[query_start_ind + args.memory_key_size:query_start_ind + args.memory_key_size + args.memory_value_size]
        else:
            query = sample['query']
            target = sample['target']
        
        query_ids = encode(query)
        target_ids = encode(target)
        qt_ids = query_ids + target_ids
        context_pairs = split_context_into_segments(context, pairs_per_segment=args.pairs_per_segment)

        segments = []
        for context_pair in context_pairs:
            context_ids = encode(context_pair)
            # print(f"[collate_fn][DEBUG] context_ids: {context_ids}")
            seg = {
                'input_ids': torch.tensor(context_ids, dtype=torch.long),
                'attention_mask': torch.ones(len(context_ids), dtype=torch.long),
                'labels': torch.full((len(context_ids),), -100, dtype=torch.long),
                'labels_mask': torch.zeros(len(context_ids), dtype=torch.bool)
            }
            segments.append(seg)

        # For query+target segment, loss only on target tokens
        qt_input_ids = torch.tensor(qt_ids, dtype=torch.long)
        qt_attention_mask = torch.ones(len(qt_ids), dtype=torch.long)
        # labels: -100 for query, target tokens as labels
        labels = torch.full((len(qt_ids),), -100, dtype=torch.long)
        if len(target_ids) > 0:
            labels[-len(target_ids):] = torch.tensor(target_ids, dtype=torch.long)
            labels_mask = torch.zeros(len(qt_ids), dtype=torch.bool)
            labels_mask[-len(target_ids) - 1:] = True
        else:
            labels_mask = torch.zeros(len(qt_ids), dtype=torch.bool)
        segments.append({
            'input_ids': qt_input_ids,
            'attention_mask': qt_attention_mask,
            'labels': labels,
            'labels_mask': labels_mask,
        })
        segments_batch.append(segments)

    # Pad segments across the batch
    batch_segments = []
    num_segments = len(segments_batch[0])
    id_pad_value = tokenizer.pad_token_id if hasattr(tokenizer, "pad_token_id") and tokenizer.pad_token_id is not None else 0
    for i in range(num_segments):
        input_ids = [s[i]['input_ids'] for s in segments_batch]
        attention_mask = [s[i]['attention_mask'] for s in segments_batch]
        labels = [s[i]['labels'] for s in segments_batch]
        labels_mask = [s[i]['labels_mask'] for s in segments_batch]

        input_ids = pad_sequence(input_ids, batch_first=True, padding_value=id_pad_value)
        attention_mask = pad_sequence(attention_mask, batch_first=True, padding_value=0)
        labels = pad_sequence(labels, batch_first=True, padding_value=-100)
        labels_mask = pad_sequence(labels_mask, batch_first=True, padding_value=False)

        batch_segment = {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'labels': labels,
            'labels_mask': labels_mask
        }
        batch_segments.append(batch_segment)

    full_labels = torch.cat([s['labels'] for s in batch_segments], dim=1)

    return {"segments": batch_segments, "labels": full_labels}

def compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer):
    # Shift logits and labels for next-token prediction
    predictions, labels, inputs = eval_pred.predictions, eval_pred.label_ids, eval_pred.inputs
    # logits, inner_loop_stats = predictions
    logits = predictions
    logits = logits[..., :-1, :]
    labels = labels[..., 1:]
    preds = np.argmax(logits, axis=-1)

    # Create a mask for tokens that are not padding (-100) and ignored tokens (like ! and |)
    mask = (labels != -100)
    for t_id in ignore_token_ids:
        mask &= (labels != t_id)

    # Calculate token-level accuracy only on content tokens
    masked_predictions = preds[mask]
    masked_labels = labels[mask]

    accuracy = (masked_predictions == masked_labels).mean()

    # get exact_match per-sample accuracy, ignore masked tokens
    decoded_labels = [tokenizer.decode(label[label != -100], skip_special_tokens=True).replace(' ', '') for label in labels]
    memory_task_mask = [decoded_labels[i][:2] == '!?' for i in range(len(decoded_labels))]

    exact_match_memory_task = np.mean([
        np.all(pred[mask[i]] == lab[mask[i]])
        for i, (pred, lab) in enumerate(zip(preds, labels))
        if np.any(mask[i]) and memory_task_mask[i]
    ])

    exact_match_base = np.mean([
        np.all(pred[mask[i]] == lab[mask[i]])
        for i, (pred, lab) in enumerate(zip(preds, labels))
        if np.any(mask[i]) and not memory_task_mask[i]
    ])

    n_samples = 5
    for pred, label, inp in zip(preds[:n_samples], labels[:n_samples],
                                         inputs[:n_samples]):
        mask = (label != -100)
        pred = pred[mask]
        inp[inp == -100] = 0
        label[label == -100] = 0
        print('i:', tokenizer.decode(inp, skip_special_tokens=True).replace(' ', ''))
        print('p:', tokenizer.decode(pred, skip_special_tokens=True).replace(' ', ''))
        print('t:', tokenizer.decode(label, skip_special_tokens=True).replace(' ', ''))
        print('-' * 50)

    res = {
        "token_accuracy": float(accuracy),
        # "exact_match": float(exact_match),
        "exact_match": float(exact_match_base),
    }
    res[f"exact_match_{args.memory_task}"] = float(exact_match_memory_task)
    return res

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
    n_layer: Optional[int] = field(default=4)
    n_head: Optional[int] = field(default=4)
    n_embd: Optional[int] = field(default=128)
    # RMT parameters
    n_mem_tokens: Optional[int] = field(default=8)
    n_ctrl_tokens: Optional[int] = field(default=0)
    use_mem_proj: Optional[bool] = field(default=False)
    mem_proj_mode: Optional[str] = field(default="none")
    memory_task_freq: Optional[float] = field(default=0.0)
    memory_task: Optional[str] = field(default=None)
    memory_key_size: Optional[int] = field(default=4)
    memory_value_size: Optional[int] = field(default=4)
    model_cpt: Optional[str] = field(default=None)
    pairs_per_segment: Optional[int] = field(default=None)
    n_pairs: Optional[int] = field(default=None)
    n_keys: Optional[int] = field(default=None)
    n_values: Optional[int] = field(default=None)


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
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)

    # create model config
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

    # # Create gradmemgpt model
    # model = GradMemGPT(config, n_mem_tokens=args.n_mem_tokens, K=args.K, lr=args.inner_lr,
    #                    use_adam=args.use_adam, grad_mode=args.grad_mode, n_ctrl_tokens=args.n_ctrl_tokens,
    #                    inner_clip_value=args.inner_clip_value, inner_clip_norm=args.inner_clip_norm,
    #                    use_mem_proj=args.use_mem_proj, mem_proj_mode=args.mem_proj_mode,
    #                    use_write_head=args.use_write_head)
    # Load model class dynamically
    # Load RMCA with cross-attention
    from modeling_rmt.huggingface_rmca_v2_gating import RMCABase, RMCAConfig

    rmt_config = RMCAConfig()
    rmt_config.base_model_config = config
    rmt_config.num_mem_tokens = args.n_mem_tokens
    rmt_config.num_mem_heads = config.num_attention_heads
    rmt_config.max_n_segments = 10
    rmt_config.think_token_id = tokenizer.convert_tokens_to_ids('[THINK]')
    rmt_config.answer_token_id = tokenizer.convert_tokens_to_ids('[ANSWER]')
    rmt_config.bos_token_id = tokenizer.convert_tokens_to_ids('[BOS]')
    rmt_config.eos_token_id = tokenizer.convert_tokens_to_ids('[EOS]')

    model = RMCABase(rmt_config)
    model.main_input_name = 'labels'

    if args.model_cpt and args.model_cpt != 'None':
        # cpt = torch.load(args.model_cpt, map_location='cpu', weights_only=False)
        # model.load_state_dict(cpt, strict=False)
        # logger.info(f'Loaded RMT state dict from: {args.model_cpt}')
        # if "safetensors" in args.model_cpt:
        #     print(model)
        #     from safetensors.torch import load_model
        #     load_model(model, args.model_cpt, device="cuda:0")
        # else:
        #     if ".bin" in args.model_cpt:
        #         model_cpt = args.model_cpt
        #     elif "model_best" in os.listdir(args.model_cpt):
        #         model_cpt = os.path.join(args.model_cpt, "model_best", "pytorch_model.bin")
        #     else:
        #         dir_files = os.listdir(args.model_cpt)
        #         print(f"Looking for a checkpoint in {args.model_cpt}: \n{dir_files}")
        #         checkpoint_dir = [el for el in dir_files if "checkpoint-" in el][0]
        #         model_cpt = os.path.join(args.model_cpt, checkpoint_dir, "pytorch_model.bin")
        #         if not os.path.exists(model_cpt):
        #             model_cpt = os.path.join(args.model_cpt, checkpoint_dir, "model.safetensors")
        #             from safetensors.torch import load_model
        #             load_model(model, args.model_cpt, device="cuda:0")
                                        
        #     cpt = torch.load(model_cpt, map_location='cpu')
        import os

        # Determine if model_cpt is a file or a directory
        model_cpt_path = args.model_cpt
        use_safetensors = False

        # If input is a directory, check its contents
        if os.path.isdir(model_cpt_path):
            dir_files = os.listdir(model_cpt_path)

            # Prefer model_best
            if "model_best" in dir_files:
                candidate = os.path.join(model_cpt_path, "model_best", "pytorch_model.bin")
                if os.path.exists(candidate):
                    model_cpt_path = candidate
                else:
                    # Try safetensors in model_best
                    candidate_st = os.path.join(model_cpt_path, "model_best", "model.safetensors")
                    if os.path.exists(candidate_st):
                        model_cpt_path = candidate_st
                        use_safetensors = True
                    else:
                        raise FileNotFoundError(f"No .bin or .safetensors found in '{os.path.join(model_cpt_path, 'model_best')}'")
            # Otherwise look for checkpoint- directories
            else:
                checkpoints = [el for el in dir_files if el.startswith("checkpoint-")]
                if not checkpoints:
                    raise FileNotFoundError(f"No checkpoint- directory found in '{model_cpt_path}'")
                checkpoint_dir = os.path.join(model_cpt_path, sorted(checkpoints)[-1])
                # Prefer bin first
                candidate = os.path.join(checkpoint_dir, "pytorch_model.bin")
                if os.path.exists(candidate):
                    model_cpt_path = candidate
                else:
                    # Try safetensors
                    candidate_st = os.path.join(checkpoint_dir, "model.safetensors")
                    if os.path.exists(candidate_st):
                        model_cpt_path = candidate_st
                        use_safetensors = True
                    else:
                        raise FileNotFoundError(f"No .bin or .safetensors found in '{checkpoint_dir}'")

        # If input is a file, check the extension
        elif os.path.isfile(model_cpt_path):
            if model_cpt_path.endswith(".safetensors"):
                use_safetensors = True
            elif model_cpt_path.endswith(".bin"):
                use_safetensors = False
            else:
                raise ValueError(f"Unknown model checkpoint file type: {model_cpt_path}")
        else:
            raise FileNotFoundError(f"Checkpoint path does not exist: {model_cpt_path}")

        # Actually load the checkpoint
        if use_safetensors:
            from safetensors.torch import load_model
            load_model(model, model_cpt_path, device="cuda:0")
        else:
            cpt = torch.load(model_cpt_path, map_location='cpu')
            # Allow possible mismatch in keys (strict=False) for flexibility
            model.load_state_dict(cpt, strict=False)
        print(f"Loaded model checkpoint from {model_cpt_path}")

    logger.info(f'model config: {model.config}')
    logger.info(f'model: {model}')
    logger.info(f"number of model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # Try to load existing dataset, otherwise generate it
    # data_path = "/workspace-SR006.nfs2/bulatov/rmt/data/associative_retrieval"
    # dataset_name = f"N{args.n_pairs}-K{args.n_keys}V{args.n_values}-V62_1M"
    # data_path = f"./data/associative_retrieval/{dataset_name}"
    try:
        logger.info(f'Attempting to load dataset from: {args.data_path}')
        dataset = datasets.load_from_disk(args.data_path)
        logger.info(f'Successfully loaded existing dataset from {args.data_path}')
    except Exception as e:
        logger.info(f'Could not load dataset from {args.data_path}: {e}')
        from kv_dataset_utils import generate_sequence
        
        # Generate samples with all fields needed for collate_fn
        logger.info('Generating raw samples...')
        raw_samples = [
            generate_sequence(num_kv_pairs=args.n_pairs,
                              n_segments=1,
                              min_segment_len = 0,
                              max_segment_len = 0,
                              k_length=args.n_keys, v_length=args.n_values)
            for _ in range(1_005_000)
        ]
        
        # Convert to HuggingFace dataset format with context, query, target fields
        import datasets as ds
        dataset_dict = {
            'context': [s['context'] for s in raw_samples],
            'query': [s['query'] for s in raw_samples],
            'target': [s['target'] for s in raw_samples],
        }
        dataset = ds.Dataset.from_dict(dataset_dict)
        dataset = dataset.train_test_split(test_size=5_000, seed=args.seed)
        # Ensure test set is called "valid" (for legacy code compatibility)
        if "test" in dataset:
            dataset = datasets.DatasetDict({
                "train": dataset["train"],
                "valid": dataset["test"],
            })
        dataset.save_to_disk(args.data_path)
        logger.info(f'Successfully generated dataset with {len(dataset["train"])} train samples and {len(dataset["valid"])} validation samples')

    # Target sequence looks like: "XXXX!|"
    # Let's not count ! and | in the accuracy calculation
    ignore_token_ids = [tokenizer.convert_tokens_to_ids(t) for t in ['!', '|']]

    # Define custom compute metrics function with ignored tokens
    def compute_metrics(eval_preds):
        return compute_metrics_fn(eval_preds, ignore_token_ids, tokenizer)

    output_dir = Path(args.exp_path)

    if args.total_batch_size is None:
        args.total_batch_size = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
    else:
        args_total_bs = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
        assert args.total_batch_size == args_total_bs

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        logging_dir=str(output_dir),

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
        # include_for_metrics=['segments', 'labels'],
        # include_for_metrics=['input_ids', 'labels', 'labels_mask'],
        save_total_limit=1,
        dataloader_num_workers=4,
        dataloader_pin_memory=True,
        seed=args.seed,
    )

    # Initialize Trainer
    trainer = CustomTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset['train'],
        eval_dataset=dataset['valid'],
        data_collator=collate_fn,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience),
                   StopOnMetricValue(metric_name='exact_match', value=0.99, higher_is_better=True),
                #    StopOnMetricValue(metric_name='exact_match_base', value=0.99, higher_is_better=True),
                   ],
    )
    # Train the model
    trainer.train()
    logger.info('training done. running final evaluation...')
    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f'{metrics}')
    trainer.save_metrics(split='all', metrics=metrics)
