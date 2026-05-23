import json
import logging
import math
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
    AutoTokenizer,
    AutoModelForCausalLM,
    Trainer, TrainerState,
    TrainingArguments,
    EarlyStoppingCallback, TrainerCallback,
    HfArgumentParser
)
from transformers.trainer_utils import get_last_checkpoint

os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")

# Register native FLA models so AutoModelForCausalLM can find them
import fla.models.mamba          # noqa: F401  registers MambaConfig / MambaForCausalLM
import fla.models.mamba2         # noqa: F401  registers Mamba2Config / Mamba2ForCausalLM
import fla.models.gated_deltanet # noqa: F401  registers GatedDeltaNetConfig / GatedDeltaNetForCausalLM
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

# Maps --base_model CLI value → config class
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


def build_fla_config(base_model: str, args, tokenizer):
    """Build the native FLA config for *base_model* from CLI args."""
    common = dict(
        vocab_size=tokenizer.vocab_size,
        hidden_size=args.n_embd,
        num_hidden_layers=args.n_layer,
        pad_token_id=tokenizer.pad_token_id,
        use_cache=False,
        # let HF Trainer compute loss from logits; avoid fused triton CE kernel
        fuse_cross_entropy=False,
    )

    if base_model in ("mamba", "mamba2"):
        if args.state_size is not None:
            common["state_size"] = args.state_size
        if args.conv_kernel is not None:
            common["conv_kernel"] = args.conv_kernel

    elif base_model == "gated_delta_net":
        # GatedDeltaNetConfig has no state_size; recurrent state = num_heads * head_dim.
        # Map: head_dim = state_size // num_heads  (so total state matches the custom wrapper).
        common["num_heads"] = args.n_head
        if args.state_size is not None and args.n_head:
            common["head_dim"] = args.state_size // args.n_head
        if args.conv_kernel is not None:
            common["conv_size"] = args.conv_kernel  # GDN uses conv_size, not conv_kernel

    elif base_model in ("delta_net", "gla", "hgrn", "hgrn2", "rwkv6", "rwkv7", "retention"):
        common["num_heads"] = args.n_head
        if args.state_size is not None:
            common["state_size"] = args.state_size
        if args.conv_kernel is not None:
            common.setdefault("conv_kernel", args.conv_kernel)

    cfg_cls = FLA_DEFAULT_CONFIGS[base_model]
    # Filter to only the kwargs accepted by this config class to avoid errors
    import inspect
    valid = set(inspect.signature(cfg_cls.__init__).parameters.keys()) - {"self", "kwargs"}
    filtered = {k: v for k, v in common.items() if k in valid}
    # Always pass unknown kwargs through __init__ **kwargs if they're not in valid
    # (most FLA configs accept **kwargs), so pass everything
    return cfg_cls(**common)


def collate_fn(batch, tokenizer, max_input_length=None):
    seq = [item['context'] + item['query'] + item['target'] for item in batch]
    seq_encoded = tokenizer(seq, return_tensors="pt", add_special_tokens=True,
                            padding=True, pad_to_multiple_of=8, max_length=max_input_length, truncation=True,
                            return_offsets_mapping=True)
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
    return {
        'input_ids': input_ids,
        'attention_mask': attn_mask,
        'labels': labels,
    }


def preprocess_logits_for_metrics(logits, labels):
    return logits.argmax(dim=-1)


def compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer):
    predictions, labels, inputs = eval_pred.predictions, eval_pred.label_ids, eval_pred.inputs

    predictions = predictions[..., :-1]
    labels = labels[..., 1:]

    mask = (labels != -100)
    for t_id in ignore_token_ids:
        mask &= (labels != t_id)
    masked_predictions = predictions[mask]
    masked_labels = labels[mask]

    accuracy = (masked_predictions == masked_labels).mean()

    exact_match = np.mean([
        np.all(pred[mask[i]] == lab[mask[i]])
        for i, (pred, lab) in enumerate(zip(predictions, labels))
        if np.any(mask[i])
    ])

    for pred, label, inp in zip(predictions[:5], labels[:5], inputs[:5]):
        mask = (label != -100)
        pred = pred[mask]
        inp[inp == -100] = tokenizer.pad_token_id
        label[label == -100] = tokenizer.pad_token_id
        print('i:', tokenizer.decode(inp, skip_special_tokens=True).strip())
        print('p:', tokenizer.decode(pred, skip_special_tokens=True).strip())
        print('t:', tokenizer.decode(label, skip_special_tokens=True).strip())
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
        num_training_steps = int(num_training_steps / 0.9)
        return super().create_scheduler(num_training_steps, optimizer)

    def log(self, logs: Dict[str, float], start_time: Optional[float] = None) -> None:
        for cb in self.callback_handler.callbacks:
            if isinstance(cb, EarlyStoppingCallback):
                logs['patience'] = cb.early_stopping_patience_counter
                break
        return super().log(logs, start_time=start_time)


@dataclass
class ExperimentArgs:
    exp_path: str = field()
    per_device_batch_size: int = field()
    data_path: str = field(default='./data/N2-K4V4-S4(32-64)_1M')
    tokenizer_path: str = field(default='./tokenizers/kv_alphabet_62/')
    gradient_accumulation_steps: Optional[int] = field(default=1)
    total_batch_size: Optional[int] = field(default=None)
    metric_for_best_model: Optional[str] = field(default='token_accuracy')
    warmup_steps: Optional[int] = field(default=1000)
    max_steps: Optional[int] = field(default=50000)
    logging_steps: Optional[int] = field(default=100)
    eval_steps: Optional[int] = field(default=100)
    weight_decay: Optional[float] = field(default=0.0)
    learning_rate: Optional[float] = field(default=1e-04)
    adam_beta1: Optional[float] = field(default=0.9)
    adam_beta2: Optional[float] = field(default=0.999)
    adam_epsilon: Optional[float] = field(default=1e-8)
    lr_scheduler_type: Optional[str] = field(default='constant_with_warmup')
    early_stopping_patience: Optional[int] = field(default=50)
    seed: Optional[int] = field(default=142)
    base_model: Optional[str] = field(default=None)
    pretrained_model: Optional[str] = field(default=None)
    n_layer: Optional[int] = field(default=4)
    n_head: Optional[int] = field(default=1)
    n_embd: Optional[int] = field(default=128)
    state_size: Optional[int] = field(default=None)
    conv_kernel: Optional[int] = field(default=None)
    max_position_embeddings: Optional[int] = field(default=None)
    max_input_length: Optional[int] = field(default=None)
    attn_implementation: Optional[str] = field(default=None)
    # Data generation parameters
    n_pairs: Optional[int] = field(default=None)
    n_keys: Optional[int] = field(default=None)
    n_values: Optional[int] = field(default=None)
    # allow writing to existing folder & resume
    overwrite_output_dir: Optional[bool] = field(default=False)
    # skip training; evaluate best checkpoint
    do_eval_only: Optional[bool] = field(default=False)


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

    assert not (args.pretrained_model is not None and args.base_model is not None), \
        "only one of --pretrained_model / --base_model must be set"

    output_dir = Path(args.exp_path)
    if accel.is_main_process and output_dir.exists() and not args.overwrite_output_dir and not args.do_eval_only:
        raise RuntimeError(
            f"Output directory already exists: {output_dir}. "
            f"Pass --overwrite_output_dir to resume/continue here, or choose a new --exp_path."
        )

    if accel.is_main_process and not args.do_eval_only:
        config = {'cli_args': dict(vars(args))}
        logger.info('saving experiment configuration..')
        Path(args.exp_path).mkdir(parents=True, exist_ok=True)
        json.dump(config, open(os.path.join(args.exp_path, 'config.json'), 'w'), indent=4)

    if accel.mixed_precision == 'bf16':
        dtype = torch.bfloat16
    elif accel.mixed_precision == 'fp16':
        dtype = torch.float16
    else:
        dtype = torch.float32
        args.attn_implementation = None

    if args.pretrained_model is not None:
        tokenizer = AutoTokenizer.from_pretrained(args.pretrained_model)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token_id = tokenizer.eos_token_id
        model = AutoModelForCausalLM.from_pretrained(
            args.pretrained_model, torch_dtype=dtype,
            attn_implementation=args.attn_implementation,
        )
    else:
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
        tokenizer.truncation_side = 'left'

        if args.base_model not in FLA_DEFAULT_CONFIGS:
            raise ValueError(
                f"Unknown --base_model '{args.base_model}'. "
                f"Supported: {sorted(FLA_DEFAULT_CONFIGS.keys())}"
            )

        cfg = build_fla_config(args.base_model, args, tokenizer)
        model = AutoModelForCausalLM.from_config(cfg)

    model.config.use_cache = False

    logger.info(f'model config: {model.config}')
    logger.info(f'model: {model}')
    logger.info(f"number of model parameters: {sum(p.numel() for p in model.parameters()):,}")
    logger.info(f'model.dtype: {model.dtype}')

    # Load or generate dataset
    try:
        logger.info(f'Attempting to load dataset from: {args.data_path}')
        dataset = datasets.load_from_disk(args.data_path)
        logger.info(f'Successfully loaded existing dataset from {args.data_path}')
    except Exception as e:
        logger.info(f'Could not load dataset from {args.data_path}: {e}')
        # noisy-AR datasets must be built explicitly — see scripts/assoc-comp-noisy-ar/00_build_data.sh
        import re as _re
        _noisy = _re.search(r'_K\d+(-vary)?-B\d+_', str(args.data_path if hasattr(args, 'data_path') else data_path))
        if _noisy:
            raise FileNotFoundError(
                f"noisy-AR dataset not present and refusing to auto-generate clean data at "
                f"{args.data_path if hasattr(args, 'data_path') else data_path}. "
                f"Build it first: bash scripts/assoc-comp-noisy-ar/00_build_data.sh"
            )
        from kv_dataset_utils import generate_sequence

        logger.info('Generating raw samples...')
        raw_samples = [
            generate_sequence(
                num_kv_pairs=args.n_pairs,
                n_segments=1,
                min_segment_len=0,
                max_segment_len=0,
                k_length=args.n_keys,
                v_length=args.n_values,
            )
            for _ in range(1_005_000)
        ]

        import datasets as ds
        dataset_dict = {
            'context': [s['context'] for s in raw_samples],
            'query':   [s['query']   for s in raw_samples],
            'target':  [s['target']  for s in raw_samples],
        }
        dataset = ds.Dataset.from_dict(dataset_dict)
        dataset = dataset.train_test_split(test_size=5_000, seed=args.seed)
        if "test" in dataset:
            dataset = datasets.DatasetDict({
                "train": dataset["train"],
                "valid": dataset["test"],
            })
        dataset.save_to_disk(args.data_path)
        logger.info(
            f'Generated dataset with {len(dataset["train"])} train '
            f'and {len(dataset["valid"])} validation samples'
        )

    def data_collator(batch):
        return collate_fn(batch, tokenizer, max_input_length=args.max_input_length)

    ignore_token_ids = [tokenizer.convert_tokens_to_ids(t) for t in ['!', '|']]

    def compute_metrics(eval_pred):
        return compute_metrics_fn(eval_pred, ignore_token_ids, tokenizer)

    if args.total_batch_size is None:
        args.total_batch_size = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
    else:
        args_total_bs = args.per_device_batch_size * accel.num_processes * args.gradient_accumulation_steps
        assert args.total_batch_size == args_total_bs

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
        adam_beta1=args.adam_beta1,
        adam_beta2=args.adam_beta2,
        adam_epsilon=args.adam_epsilon,
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
        include_num_input_tokens_seen=True,
        include_for_metrics=['inputs'],
        save_total_limit=1,
        dataloader_num_workers=4,
        dataloader_pin_memory=True,
        seed=args.seed,
    )

    trainer = CustomTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset['train'],
        eval_dataset=dataset['valid'],
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        preprocess_logits_for_metrics=preprocess_logits_for_metrics,
        callbacks=[
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience),
            StopOnMetricValue(metric_name='exact_match', value=1.0, higher_is_better=True),
        ],
    )

    last_ckpt = get_last_checkpoint(output_dir)

    if args.do_eval_only:
        try:
            state_path = Path(last_ckpt) / "trainer_state.json"
            trainer.state = TrainerState.load_from_json(state_path)
            trainer._load_best_model()
            logger.info(f'Successfully loaded best model from {trainer.state.best_model_checkpoint}')
        except Exception as e:
            logger.error(f"Failed to load best model from {output_dir}: {e}")
            exit(1)
    else:
        if last_ckpt:
            logger.info(f'Resuming training from last checkpoint: {last_ckpt}')
        trainer.train(resume_from_checkpoint=last_ckpt)
        logger.info('training done. running final evaluation...')

    metrics = trainer.evaluate(dataset['valid'])
    logger.info(f'{metrics}')
    trainer.save_metrics(split='all', metrics=metrics)
    if not args.do_eval_only:
        trainer.state.save_to_json(output_dir / 'trainer_state.json')
