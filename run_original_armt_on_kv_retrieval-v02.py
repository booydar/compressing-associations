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
    """
    Collate function that splits each sample into two segments:
    - First segment: context
    - Second segment: query + target
    Pads segments across the batch to the same length.
    Returns a dict matching the ARMT forward interface:
        input_ids: (batch, n_segments, seq_len)
        attention_mask: (batch, n_segments, seq_len)
        labels: (batch, n_segments, seq_len)
        labels_mask: (batch, n_segments, seq_len)
        input_segmented: True
    """
    from torch.nn.utils.rnn import pad_sequence
    import torch

    # Helper to encode a string to ids
    def encode(text):
        return tokenizer.encode(text, add_special_tokens=False)

    # Prepare segments for each sample
    seg_input_ids = []
    seg_attention_mask = []
    seg_labels = []
    seg_labels_mask = []

    for sample in batch:
        context = sample['context']
        query = sample['query']
        target = sample['target']

        # Segment 1: context
        context_ids = encode(context)
        # Segment 2: query + target
        query_ids = encode(query)
        target_ids = encode(target)
        qt_ids = query_ids + target_ids

        # For context segment, no loss (labels = -100)
        seg1_input_ids = torch.tensor(context_ids, dtype=torch.long)
        seg1_attention_mask = torch.ones(len(context_ids), dtype=torch.long)
        seg1_labels = torch.full((len(context_ids),), -100, dtype=torch.long)
        seg1_labels_mask = torch.zeros(len(context_ids), dtype=torch.bool)

        # For query+target segment, loss only on target tokens
        seg2_input_ids = torch.tensor(qt_ids, dtype=torch.long)
        seg2_attention_mask = torch.ones(len(qt_ids), dtype=torch.long)
        seg2_labels = torch.full((len(qt_ids),), -100, dtype=torch.long)
        seg2_labels_mask = torch.zeros(len(qt_ids), dtype=torch.bool)
        if len(target_ids) > 0:
            seg2_labels[-len(target_ids):] = torch.tensor(target_ids, dtype=torch.long)
            seg2_labels_mask[-len(target_ids):] = True

        seg_input_ids.append([seg1_input_ids, seg2_input_ids])
        seg_attention_mask.append([seg1_attention_mask, seg2_attention_mask])
        seg_labels.append([seg1_labels, seg2_labels])
        seg_labels_mask.append([seg1_labels_mask, seg2_labels_mask])

    # Now pad each segment across the batch, then stack into (batch, n_segments, seq_len)
    num_segments = 2
    id_pad_value = tokenizer.pad_token_id if hasattr(tokenizer, "pad_token_id") and tokenizer.pad_token_id is not None else 0

    def pad_and_stack(segment_list, pad_value):
        # segment_list: list of [seg1, seg2] for each sample
        segs = []
        for seg_idx in range(num_segments):
            seg_items = [sample[seg_idx] for sample in segment_list]
            seg_padded = pad_sequence(seg_items, batch_first=True, padding_value=pad_value)
            segs.append(seg_padded)
        # segs: list of (batch, seg_len) for each segment
        # Stack to (batch, n_segments, seg_len_max)
        max_len = max(s.size(1) for s in segs)
        segs_padded = []
        for s in segs:
            if s.size(1) < max_len:
                pad_amt = max_len - s.size(1)
                s = torch.nn.functional.pad(s, (0, pad_amt), value=pad_value)
            segs_padded.append(s)
        stacked = torch.stack(segs_padded, dim=1)  # (batch, n_segments, seg_len_max)
        return stacked

    input_ids = pad_and_stack(seg_input_ids, id_pad_value)
    attention_mask = pad_and_stack(seg_attention_mask, 0)
    labels = pad_and_stack(seg_labels, -100)
    labels_mask = pad_and_stack(seg_labels_mask, False)

    # Print sanity checks for debugging
    # print("[collate_fn] input_ids shape:", input_ids.shape)
    # print("[collate_fn] attention_mask shape:", attention_mask.shape)
    # print("[collate_fn] labels shape:", labels.shape)
    # print("[collate_fn] labels_mask shape:", labels_mask.shape)
    # print("[collate_fn] input_ids example:", input_ids[0] if input_ids.shape[0] > 0 else None)
    # print("[collate_fn] labels example:", labels[0] if labels.shape[0] > 0 else None)
    # print("[collate_fn] labels_mask example:", labels_mask[0] if labels_mask.shape[0] > 0 else None)

    # For ARMT forward, input_segmented=True, and all tensors are (batch, n_segments, seq_len)
    return {
        # "input_ids": torch.stack([input_ids[:, 0], input_ids[:, 1]], dim=1),
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels,
        "labels_mask": labels_mask,
        "input_segmented": True
    }

def compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer):
    # Debug: Print eval_pred structure
    print(f"[compute_metrics_fn] eval_pred type: {type(eval_pred)}")
    print(f"[compute_metrics_fn] eval_pred attributes: {dir(eval_pred)}")
    if hasattr(eval_pred, '__dict__'):
        print(f"[compute_metrics_fn] eval_pred.__dict__ keys: {eval_pred.__dict__.keys()}")
    
    # Unpack predictions, labels, and inputs
    predictions, labels, inputs = eval_pred.predictions, eval_pred.label_ids, eval_pred.inputs

    print(f"[compute_metrics_fn] predictions type: {type(predictions)}")
    print(f"[compute_metrics_fn] labels type: {type(labels)}")
    print(f"[compute_metrics_fn] inputs type: {type(inputs)}")

    # If predictions is a tuple (e.g., (logits, ...)), extract logits
    if isinstance(predictions, tuple):
        logits = predictions[0]
        print(f"[compute_metrics_fn] predictions is tuple, extracted logits from index 0")
    else:
        logits = predictions

    print(f"[compute_metrics_fn] logits type: {type(logits)}")
    print(f"[compute_metrics_fn] logits shape: {getattr(logits, 'shape', None)}")
    print(f"[compute_metrics_fn] labels shape: {getattr(labels, 'shape', None)}")
    print(f"[compute_metrics_fn] inputs shape: {getattr(inputs, 'shape', None)}")
    
    # Handle case where logits might be None or have unexpected shape
    if logits is None:
        print("[compute_metrics_fn] ERROR: logits is None!")
        return {"token_accuracy": 0.0, "exact_match": 0.0}
    
    if not hasattr(logits, 'shape') or logits.shape is None:
        print(f"[compute_metrics_fn] ERROR: logits has no shape attribute or shape is None! logits: {logits}")
        return {"token_accuracy": 0.0, "exact_match": 0.0}
    
    print(f"[compute_metrics_fn] logits: {logits}")
    print(f"[compute_metrics_fn] labels: {labels}")
    print(f"[compute_metrics_fn] inputs: {inputs}")

    # Handle case where logits might have unexpected shape
    if len(logits.shape) == 1:
        print(f"[compute_metrics_fn] WARNING: logits has 1D shape {logits.shape}, expected 3D (batch, seq, vocab)")
        # This might be a flattened tensor, try to reshape it
        # We need to know the vocab size to reshape properly
        # For now, return default metrics
        return {"token_accuracy": 0.0, "exact_match": 0.0}
    elif len(logits.shape) == 2:
        print(f"[compute_metrics_fn] WARNING: logits has 2D shape {logits.shape}, expected 3D (batch, seq, vocab)")
        # This might be (batch*seq, vocab) or (batch, vocab)
        # Try to infer the correct shape
        if logits.shape[0] == inputs.shape[0]:  # batch dimension matches
            # Assume it's (batch, vocab) - single token prediction
            print("[compute_metrics_fn] Assuming single token prediction")
            preds = np.argmax(logits, axis=-1)
            # For single token, we can't compute sequence-level metrics
            return {"token_accuracy": 0.0, "exact_match": 0.0}
        else:
            # Assume it's (batch*seq, vocab) - flattened
            print("[compute_metrics_fn] Assuming flattened logits")
            # Try to reshape to (batch, seq, vocab)
            batch_size = inputs.shape[0]
            seq_len = inputs.shape[1]
            vocab_size = logits.shape[-1]
            if logits.shape[0] == batch_size * seq_len:
                logits = logits.reshape(batch_size, seq_len, vocab_size)
                print(f"[compute_metrics_fn] Reshaped logits to: {logits.shape}")
            else:
                print(f"[compute_metrics_fn] Cannot reshape logits: {logits.shape} to match inputs: {inputs.shape}")
                return {"token_accuracy": 0.0, "exact_match": 0.0}
    elif len(logits.shape) != 3:
        print(f"[compute_metrics_fn] ERROR: Unexpected logits shape: {logits.shape}")
        return {"token_accuracy": 0.0, "exact_match": 0.0}
    
    # Shift logits and labels for next-token prediction
    if logits.shape[1] > 1:  # Only shift if we have more than 1 token
        logits = logits[..., :-1, :]
        labels = labels[..., 1:]
    else:
        print("[compute_metrics_fn] WARNING: Single token sequence, cannot shift for next-token prediction")
        return {"token_accuracy": 0.0, "exact_match": 0.0}
        
    preds = np.argmax(logits, axis=-1)

    print(f"[compute_metrics_fn] shifted logits shape: {getattr(logits, 'shape', None)}")
    print(f"[compute_metrics_fn] shifted labels shape: {getattr(labels, 'shape', None)}")
    print(f"[compute_metrics_fn] preds shape: {getattr(preds, 'shape', None)}")

    # Create a mask for tokens that are not padding (-100) and ignored tokens (like ! and |)
    mask = (labels != -100)
    for t_id in ignore_token_ids:
        mask &= (labels != t_id)

    print(f"[compute_metrics_fn] mask shape: {getattr(mask, 'shape', None)}")

    # Calculate token-level accuracy only on content tokens
    masked_predictions = preds[mask]
    masked_labels = labels[mask]

    print(f"[compute_metrics_fn] masked_predictions shape: {getattr(masked_predictions, 'shape', None)}")
    print(f"[compute_metrics_fn] masked_labels shape: {getattr(masked_labels, 'shape', None)}")

    accuracy = (masked_predictions == masked_labels).mean() if masked_labels.size > 0 else 0.0

    # get exact_match per-sample accuracy, ignore masked tokens
    # predictions.shape = (batch_size, seq_len)
    exact_match = np.mean([
        np.all(pred[mask[i]] == lab[mask[i]])
        for i, (pred, lab) in enumerate(zip(preds, labels))
        if np.any(mask[i])  # Skip samples that are all masked
    ]) if preds.shape[0] > 0 else 0.0

    for pred, label, inp in zip(preds[:5], labels[:5], inputs[:5]):
        mask_i = (label != -100)
        pred_i = pred[mask_i]
        inp[inp == -100] = 0
        label[label == -100] = 0
        print('i:', tokenizer.decode(inp, skip_special_tokens=True).replace(' ', ''))
        print('p:', tokenizer.decode(pred_i, skip_special_tokens=True).replace(' ', ''))
        print('t:', tokenizer.decode(label, skip_special_tokens=True).replace(' ', ''))
        print('-' * 50)

    return {
        "token_accuracy": float(accuracy),
        "exact_match": float(exact_match),
    }


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
    print(f'[config] vocab size: {config.vocab_size}')
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
    # Load RMT as in debug_rmt.ipynb
    from modeling_armt.huggingface import ARMTForCausalLM, ARMTConfig

    rmt_config = ARMTConfig()
    rmt_config.base_model_config = config
    rmt_config.num_mem_tokens = args.n_mem_tokens
    rmt_config.max_n_segments = 10
    rmt_config.think_token_id = tokenizer.convert_tokens_to_ids('[THINK]')
    rmt_config.answer_token_id = tokenizer.convert_tokens_to_ids('[ANSWER]')
    rmt_config.bos_token_id = tokenizer.convert_tokens_to_ids('[BOS]')
    rmt_config.eos_token_id = tokenizer.convert_tokens_to_ids('[EOS]')

    model = ARMTForCausalLM(rmt_config)
    model.main_input_name = 'labels'

    logger.info(f'model config: {model.config}')
    logger.info(f'model: {model}')

    dataset = datasets.load_dataset(f"yurakuratov/{args.data_path}")

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
        # include_for_metrics=['segments', 'labels'],
        # include_for_metrics=['input_ids', 'labels', 'labels_mask'],
        save_total_limit=3,
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
                   StopOnMetricValue(metric_name='exact_match', value=1.0, higher_is_better=True),
                   ],
    )
    # Train the model
    trainer.train()
    logger.info('training done. running final evaluation...')
    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f'{metrics}')
    trainer.save_metrics(split='all', metrics=metrics)
