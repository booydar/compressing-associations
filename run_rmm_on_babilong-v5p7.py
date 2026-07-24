"""RMM v5p7 (paper version) on babilong (noisy bAbI, arbitrary context length).

RMM analog of the original babilong experiment
(github.com/booydar/recurrent-memory-transformer, branch babilong-release,
run_finetuning_babilong_rmt.py): bAbI facts are scattered into `sample_size`
tokens of background text sampled from a noise corpus (pg19), and the model
must answer the question from memory after reading the noisy context.

Differences from the babi qaX_0k runners (run_rmm_on_babi-*.py, no noise):
  - data is built on the fly from raw bAbI txt (babilong_utils.TaskDataset /
    SentenceSampler / NoiseInjectionDataset) instead of load_from_disk;
  - exactly like the RMT reference, the flat sequence
    input_tokens + question_tokens + target_tokens is split into
    ceil(len / segment_size) uniform segments (parallel prefill requires
    uniform T). The question+answer ride in the LAST context segment (they
    self-attend together with the context tail, and read earlier context via
    memory) -- NOT in a dedicated extra segment. So the model sees
    max_n_segments segments, and at max_n_segments=1 it is a plain single
    causal forward over the whole sample (memory unused);
  - --vary_n_segments samples the context length per sample from
    {segment_size*1..segment_size*max_n_segments} (original curriculum trick);
  - qa_margin (build_babilong_datasets) reserves room so question+answer never
    spill past the segment budget into an extra segment.

Context tokens are RIGHT-aligned: with mixed lengths in a batch the padding
goes into the EARLIEST segments, so memory written from all-pad segments is
overwritten by the real segments before the question tokens arrive.

Prereq: bash scripts/babilong/download_babilong_data.sh
"""
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
    AutoConfig, AutoTokenizer,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback, TrainerCallback,
    HfArgumentParser
)

from babilong_utils import TaskDataset, SentenceSampler, NoiseInjectionDataset

os.environ['TOKENIZERS_PARALLELISM'] = 'false'

logger_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
log_lvl = logging.INFO
logging.basicConfig(format=logger_fmt, level=log_lvl)
logger = logging.getLogger('')

logger.info(f"CUDA DEVICE COUNT: {torch.cuda.device_count()}")


def collate_babilong(batch, tokenizer, segment_size):
    """babilong sample (input_tokens/question_tokens/target_tokens) ->
    RMM segment list of S = ceil(max_len / segment_size) uniform segments.

    Matches the RMT reference (run_finetuning_babilong_rmt.py): the flat
    sequence  input_tokens + question_tokens + target_tokens  is right-aligned
    into uniform segments. The question+answer land in the LAST segment (which
    the model runs as its query segment: self-attention over the context tail +
    question + answer, plus a memory read of the earlier segments) -- there is
    NO dedicated extra question segment. labels cover the answer tokens only;
    labels_mask is the predict-next shift (position p is in the loss iff token
    p+1 is a target token). qa_margin (build_babilong_datasets) guarantees the
    question+answer fit inside the segment budget, so S <= max_n_segments.
    """
    pad_id = tokenizer.pad_token_id
    B = len(batch)
    T = segment_size

    seqs, tgt_lens = [], []
    for b in batch:
        q, t = list(b['question_tokens']), list(b['target_tokens'])
        seqs.append(list(b['input_tokens']) + q + t)
        tgt_lens.append(len(t))

    S = max(1, math.ceil(max(len(s) for s in seqs) / T))
    L = S * T
    input_ids = torch.full((B, L), pad_id, dtype=torch.long)
    attention_mask = torch.zeros((B, L), dtype=torch.long)
    labels = torch.full((B, L), -100, dtype=torch.long)
    labels_mask = torch.zeros((B, L), dtype=torch.bool)
    for i, (s, tl) in enumerate(zip(seqs, tgt_lens)):
        s = s[-L:]  # safety; qa_margin keeps len(s) <= S*T
        n = len(s)
        row = torch.tensor(s, dtype=torch.long)
        input_ids[i, L - n:] = row
        attention_mask[i, L - n:] = 1
        # answer tokens are the last tl tokens of the right-aligned sequence
        labels[i, L - tl:] = row[-tl:]
        # predict-next: position p is in the loss iff token p+1 is a target token
        labels_mask[i, L - tl - 1: L - 1] = True

    segments = []
    for s in range(S):
        sl = slice(s * T, (s + 1) * T)
        segments.append({
            'input_ids': input_ids[:, sl],
            'attention_mask': attention_mask[:, sl],
            'labels': labels[:, sl],
            'labels_mask': labels_mask[:, sl],
        })
    full_labels = torch.cat([s['labels'] for s in segments], dim=1)
    return {"segments": segments, "labels": full_labels}


def collate_fn(batch):
    return collate_babilong(batch, tokenizer, args.segment_size)


def preprocess_logits_for_metrics(logits, labels):
    # streameval returns (B, S*T) int predictions; leave those untouched
    return logits if logits.dim() == 2 else logits.argmax(dim=-1)


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
        print('i:', tokenizer.decode(inp, skip_special_tokens=True).strip()[-500:])
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
    # babilong data
    babi_path:                str            = field(default='./data/tasks_1-20_v1-2/en-10k')
    task_dataset:             str            = field(default='qa1_single-supporting-fact')
    noise_dataset:            str            = field(default='emozilla/pg19')
    noise_dataset_config:     Optional[str]  = field(default=None)
    max_n_facts:              Optional[int]  = field(default=None)
    task_start_pct:           Optional[float]= field(default=None)
    task_end_pct:             Optional[float]= field(default=None)
    # segmentation
    segment_size:             Optional[int]  = field(default=512)
    max_n_segments:           Optional[int]  = field(default=8)   # total segments; question+answer ride in the last one
    sample_size:              Optional[int]  = field(default=None)  # default: segment_size * max_n_segments
    vary_n_segments:          Optional[bool] = field(default=False)
    mixed_length_ratio:       Optional[float]= field(default=0.0)
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
    use_parallel_prefill:     Optional[bool] = field(default=True)
    eval_stream_logits:       Optional[bool] = field(default=False)  # memory-frugal recurrent eval (streameval modeling variant)
    model_cpt:                Optional[str]  = field(default=None)
    validate_only:            Optional[bool] = field(default=False)  # load model_cpt, eval on test only (no train, no model_best.pt overwrite)


def build_rmm_model(args, tokenizer):
    if getattr(args, 'eval_stream_logits', False):
        from modeling_rmt.huggingface_rmm_v5p7_streameval import RecurrentMemoryBase, RecurrentMemoryConfig
    else:
        from modeling_rmt.huggingface_rmm_v5p7 import RecurrentMemoryBase, RecurrentMemoryConfig

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
        **({'eval_stream_logits': True} if getattr(args, 'eval_stream_logits', False) else {}),
        max_n_segments     = args.max_n_segments,
        think_token_id     = None,
        answer_token_id    = None,
        bos_token_id       = tokenizer.bos_token_id,
        eos_token_id       = tokenizer.eos_token_id,
    )
    model = RecurrentMemoryBase(rmm_config)
    model.main_input_name = 'labels'
    return model


def build_babilong_datasets(args, tokenizer):
    """Original babilong recipe: noise corpus train/test -> SentenceSampler,
    raw babi txt -> TaskDataset, combined by NoiseInjectionDataset."""
    noise = datasets.load_dataset(args.noise_dataset, args.noise_dataset_config)
    noise_train = noise['train']
    noise_test = noise['test'] if 'test' in noise else noise['validation']

    train_path = os.path.join(args.babi_path, f"{args.task_dataset}_train.txt")
    test_path = os.path.join(args.babi_path, f"{args.task_dataset}_test.txt")
    task_train = TaskDataset(train_path, max_n_facts=args.max_n_facts)
    task_test = TaskDataset(test_path, max_n_facts=args.max_n_facts)

    # reserve room so question+answer fit inside the segment budget and never
    # spill into an extra segment (matches the RMT reference qa_margin=20).
    qa_margin = 20
    if args.vary_n_segments:
        train_sample_size = [args.segment_size * i for i in range(1, args.max_n_segments)] + [args.sample_size]
        train_sample_size = [s - qa_margin for s in train_sample_size]
        logger.info(f'Will be choosing train sample size randomly from {train_sample_size}')
    else:
        train_sample_size = args.sample_size - qa_margin
    test_sample_size = args.sample_size - qa_margin

    max_sentence_len = None
    if (args.task_start_pct is not None) and (args.task_end_pct is not None):
        # do not sample sentences longer than task position range * 0.5
        max_sentence_len = int((args.task_end_pct - args.task_start_pct) * 0.5 * args.sample_size)

    sampler_train = SentenceSampler(noise_train, tokenizer=tokenizer,
                                    max_sentence_len=max_sentence_len, shuffle=True, random_seed=None)
    sampler_test = SentenceSampler(noise_test, tokenizer=tokenizer,
                                   max_sentence_len=max_sentence_len, shuffle=True, random_seed=42)

    train_dataset = NoiseInjectionDataset(task_dataset=task_train, noise_sampler=sampler_train,
                                          tokenizer=tokenizer, sample_size=train_sample_size,
                                          mixed_length_ratio=args.mixed_length_ratio,
                                          task_start_pct=args.task_start_pct,
                                          task_end_pct=args.task_end_pct)
    test_dataset = NoiseInjectionDataset(task_dataset=task_test, noise_sampler=sampler_test,
                                         tokenizer=tokenizer, sample_size=test_sample_size,
                                         mixed_length_ratio=args.mixed_length_ratio,
                                         task_start_pct=args.task_start_pct,
                                         task_end_pct=args.task_end_pct)
    return train_dataset, test_dataset


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
    if args.sample_size is None:
        args.sample_size = args.segment_size * args.max_n_segments
    assert args.sample_size <= args.segment_size * args.max_n_segments, \
        f'sample_size {args.sample_size} exceeds segment budget {args.segment_size}*{args.max_n_segments}'

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
        # accept both our flat model_best.pt state_dict and an HF Trainer
        # checkpoint-XXX/model.safetensors (torch.load can't read safetensors).
        if args.model_cpt.endswith('.safetensors'):
            from safetensors.torch import load_file
            state_dict = load_file(args.model_cpt, device='cpu')
        else:
            # our own checkpoints are trusted; weights_only=False for torch>=2.6
            state_dict = torch.load(args.model_cpt, map_location='cpu', weights_only=False)
        model.load_state_dict(state_dict, strict=False)
        print(f"Loaded checkpoint: {args.model_cpt}")

    logger.info(f"parameters: {sum(p.numel() for p in model.parameters()):,}")

    train_dataset, test_dataset = build_babilong_datasets(args, tokenizer)

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
        train_dataset   = train_dataset,
        eval_dataset    = test_dataset,
        data_collator   = collate_fn,
        compute_metrics = compute_metrics,
        preprocess_logits_for_metrics = preprocess_logits_for_metrics,
        callbacks=[
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience),
            StopOnMetricValue('exact_match', 1.0, higher_is_better=True),
        ],
    )
    if args.validate_only:
        # extrapolation eval: evaluate the loaded --model_cpt on test at the
        # requested max_n_segments. No training, and model_best.pt is NOT touched.
        logger.info(f'validate_only: evaluating {args.model_cpt} at max_n_segments={args.max_n_segments}')
        metrics = trainer.evaluate(test_dataset)
        logger.info(f'{metrics}')
        if accel.is_main_process:
            trainer.save_metrics(split='all', metrics=metrics)
    else:
        trainer.train()
        accel.wait_for_everyone()
        # best weights are loaded (load_best_model_at_end); save a flat .pt for
        # curriculum chaining via --model_cpt
        if accel.is_main_process:
            torch.save(trainer.model.state_dict(), os.path.join(args.exp_path, 'model_best.pt'))
            logger.info(f"saved best model to {os.path.join(args.exp_path, 'model_best.pt')}")
        logger.info('training done. running final evaluation...')
        metrics = trainer.evaluate(test_dataset)
        logger.info(f'{metrics}')
        trainer.save_metrics(split='all', metrics=metrics)
