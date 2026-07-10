"""babilong pipeline validation: (1) babilong_utils builds noisy samples of the
requested token size with facts+question+answer intact, (2) the babilong collate
produces uniform right-aligned context segments + a final qt segment with
labels only on the answer (predict-next shift), (3) [CUDA] a tiny v6p4 model
runs forward on a collated batch with mixed lengths and returns finite loss.
Run with the fla python; (1)+(2) work on CPU, (3) needs a CUDA box."""
import importlib.util
import os
import sys
import tempfile

import numpy as np
import torch
import datasets
from transformers import AutoTokenizer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from babilong_utils import TaskDataset, SentenceSampler, NoiseInjectionDataset

_spec = importlib.util.spec_from_file_location(
    'run_rmm_on_babilong_v6p4',
    os.path.join(os.path.dirname(__file__), '..', 'run_rmm_on_babilong-v6p4.py'))
_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runner)
collate_babilong = _runner.collate_babilong

BABI_QA1 = """1 Mary moved to the bathroom.
2 John went to the hallway.
3 Where is Mary? \tbathroom\t1
1 Daniel went back to the hallway.
2 Sandra moved to the garden.
3 John moved to the office.
4 Where is Daniel? \thallway\t1
1 Sandra travelled to the office.
2 Mary went to the kitchen.
3 Where is Sandra? \toffice\t1
"""

NOISE_TEXTS = [
    ' '.join(f'This is a plain filler sentence number {i} about nothing in particular.'
             for i in range(200)),
    ' '.join(f'Another background story goes on and on with sentence {i} of little meaning.'
             for i in range(200)),
]


def build_dataset(tokenizer, sample_size, seed=42):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write(BABI_QA1)
        path = f.name
    task = TaskDataset(path)
    noise = datasets.Dataset.from_dict({'text': NOISE_TEXTS})
    sampler = SentenceSampler(noise, tokenizer=tokenizer, shuffle=True, random_seed=seed)
    return NoiseInjectionDataset(task_dataset=task, noise_sampler=sampler,
                                 tokenizer=tokenizer, sample_size=sample_size,
                                 random_seed=seed)


def test_noise_injection(tokenizer):
    sample_size = 256
    ds = build_dataset(tokenizer, sample_size)
    for i in range(len(ds)):
        s = ds[i]
        assert len(s['input_tokens']) == sample_size, \
            f'sample {i}: {len(s["input_tokens"])} != {sample_size}'
        text = tokenizer.decode(s['input_tokens'])
        for fact in s['facts']:
            assert fact in text, f'fact lost: {fact}'
        assert tokenizer.decode(s['question_tokens']) == s['question']
        assert tokenizer.decode(s['target_tokens']) == s['answer']
    # vary_n_segments-style list sizes
    ds_vary = build_dataset(tokenizer, [128, 256], seed=7)
    sizes = {len(ds_vary[i]['input_tokens']) for i in range(len(ds_vary))}
    assert sizes <= {128, 256}, sizes
    print('noise injection OK')


def test_collate(tokenizer):
    T = 128
    ds = build_dataset(tokenizer, [T, 2 * T], seed=7)
    batch = [ds[i] for i in range(len(ds))]
    out = collate_babilong(batch, tokenizer, segment_size=T)
    segments = out['segments']

    max_ctx = max(len(b['input_tokens']) for b in batch)
    S = (max_ctx + T - 1) // T
    assert len(segments) == S + 1, (len(segments), S)
    B = len(batch)
    for seg in segments[:-1]:
        assert seg['input_ids'].shape == (B, T)
        assert not seg['labels_mask'].any() and (seg['labels'] == -100).all()

    # right alignment: context tokens end exactly at the last context position
    ctx_ids = torch.cat([s['input_ids'] for s in segments[:-1]], dim=1)
    ctx_mask = torch.cat([s['attention_mask'] for s in segments[:-1]], dim=1)
    for i, b in enumerate(batch):
        n = len(b['input_tokens'])
        assert ctx_mask[i].sum() == n
        assert ctx_mask[i, -n:].all(), 'context must be right-aligned'
        assert ctx_ids[i, -n:].tolist() == b['input_tokens']

    qt = segments[-1]
    for i, b in enumerate(batch):
        q, t = b['question_tokens'], b['target_tokens']
        labeled = qt['labels'][i][qt['labels'][i] != -100]
        assert labeled.tolist() == t, 'labels must cover exactly the answer tokens'
        # predict-next shift: mask at p iff p+1 is a target token
        expect_mask = torch.zeros_like(qt['labels_mask'][i])
        expect_mask[len(q) - 1: len(q) + len(t) - 1] = True
        assert (qt['labels_mask'][i] == expect_mask).all()

    assert out['labels'].shape[1] == sum(s['input_ids'].shape[1] for s in segments)
    print('collate OK')


def test_model_forward(tokenizer):
    if not torch.cuda.is_available():
        print('no CUDA, skipping model forward smoke')
        return
    from transformers import AutoConfig
    from modeling_rmt.huggingface_rmm_v6p4 import RecurrentMemoryBase, RecurrentMemoryConfig

    base = AutoConfig.from_pretrained('gpt2')
    base.n_layer, base.n_head, base.n_embd = 2, 1, 64
    base.vocab_size = tokenizer.vocab_size
    base.pad_token_id = tokenizer.pad_token_id
    base.torch_dtype = 'float32'
    base.use_cache = False
    cfg = RecurrentMemoryConfig(base_model_config=base, fla_layer_name='GatedDeltaNet',
                                num_heads=1, head_dim=32, expand_v=2.0, conv_size=4,
                                num_memory_vectors=8, write_mode='pool', read_mode='identity',
                                use_parallel_prefill=True, max_n_segments=5,
                                bos_token_id=tokenizer.bos_token_id,
                                eos_token_id=tokenizer.eos_token_id)
    model = RecurrentMemoryBase(cfg).cuda()

    T = 128
    ds = build_dataset(tokenizer, [T, 2 * T], seed=7)  # mixed lengths -> pad segments
    batch = [ds[i] for i in range(len(ds))]
    out = collate_babilong(batch, tokenizer, segment_size=T)
    segments = [{k: v.cuda() for k, v in s.items()} for s in out['segments']]
    res = model(segments=segments, labels=out['labels'].cuda())
    assert torch.isfinite(res.loss), res.loss
    assert torch.isfinite(res.logits).all(), 'non-finite logits (pad segments?)'
    print(f'model forward OK, loss={res.loss.item():.4f}')


def test_model_forward_v5p7(tokenizer):
    if not torch.cuda.is_available():
        print('no CUDA, skipping v5p7 forward smoke')
        return
    from transformers import AutoConfig
    from modeling_rmt.huggingface_rmm_v5p7 import RecurrentMemoryBase, RecurrentMemoryConfig

    T = 128
    ds = build_dataset(tokenizer, [T, 2 * T], seed=7)  # mixed lengths -> pad segments
    batch = [ds[i] for i in range(len(ds))]
    out = collate_babilong(batch, tokenizer, segment_size=T)
    segments = [{k: v.cuda() for k, v in s.items()} for s in out['segments']]

    for write_mode, read_mode in [('identity', 'identity'), ('pool', 'unpool')]:
        base = AutoConfig.from_pretrained('gpt2')
        base.n_layer, base.n_head, base.n_embd = 2, 1, 64
        base.vocab_size = tokenizer.vocab_size
        base.pad_token_id = tokenizer.pad_token_id
        base.torch_dtype = 'float32'
        base.use_cache = False
        cfg = RecurrentMemoryConfig(base_model_config=base, fla_layer_name='GatedDeltaNet',
                                    num_heads=1, head_dim=32, expand_v=2.0, conv_size=4,
                                    num_memory_vectors=16, write_mode=write_mode,
                                    read_mode=read_mode, use_parallel_prefill=True,
                                    max_n_segments=5,
                                    bos_token_id=tokenizer.bos_token_id,
                                    eos_token_id=tokenizer.eos_token_id)
        model = RecurrentMemoryBase(cfg).cuda()
        res = model(segments=[{k: v.clone() for k, v in s.items()} for s in segments],
                    labels=out['labels'].cuda())
        assert torch.isfinite(res.loss), (write_mode, read_mode, res.loss)
        assert torch.isfinite(res.logits).all(), (write_mode, read_mode)
        print(f'v5p7 {write_mode}/{read_mode} forward OK, loss={res.loss.item():.4f}')


if __name__ == '__main__':
    tokenizer = AutoTokenizer.from_pretrained('gpt2')
    tokenizer.pad_token_id = tokenizer.eos_token_id
    test_noise_injection(tokenizer)
    test_collate(tokenizer)
    test_model_forward(tokenizer)
    test_model_forward_v5p7(tokenizer)
    print('ALL OK')
