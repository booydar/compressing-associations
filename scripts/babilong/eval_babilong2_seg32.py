#!/usr/bin/env python3
"""Length-extrapolation eval of the babilong2 curriculum's 32-segment models.

babilong2 = runs produced with the *fixed* segmentation in
run_rmm_on_babilong-v5p7.py (commit "fix babilong segmentation"): the flat
sequence input+question+target is split into ceil(len/segment_size) uniform
segments and the question+answer ride in the LAST context segment, exactly like
the RMT reference -- there is no dedicated extra QT segment. Only that runner
may be used to evaluate these checkpoints.

For every <task>/<run_name> that reached the seg32 curriculum stage this script
resolves the weights that stage ended with and evaluates them (--validate_only)
at each MAX_N_SEGMENTS in the extrapolation ladder, writing metrics into
    <task>/<run_name>/eval_seg<N>_from32/run_1
so notebooks/collect_results_babilong.ipynb picks them up as src=32 rows.

Checkpoint resolution
---------------------
The cluster jobs that produced babilong2 did not ship the flat model_best.pt
files, only the HF checkpoint-XXX/model.safetensors kept by the trainer
(save_total_limit=1 + load_best_model_at_end => the surviving checkpoint is the
best one). A stage whose very first eval already hit exact_match == 1.0 is
stopped by StopOnMetricValue at step 0, so it trains for zero steps and saves
nothing; its final weights are simply the weights it warm-started from. This
script therefore walks the curriculum ladder back from seg32 and takes the
deepest stage that actually saved a checkpoint -- which is, bit for bit, the
model the seg32 stage ended with.

Usage
-----
  python scripts/babilong/eval_babilong2_seg32.py --list
  CUDA_VISIBLE_DEVICES=0 python scripts/babilong/eval_babilong2_seg32.py \
      --tasks qa1 --eval-segments 1 2 4 8 16 32 64 128 256
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = 'run_rmm_on_babilong-v5p7.py'
# STAGES = [1, 2, 4, 6, 8, 16, 32]
# DEFAULT_EVAL_SEGMENTS = [1, 2, 4, 8, 16, 32, 64, 128, 256]
DEFAULT_EVAL_SEGMENTS = [64, 128, 256]
STAGES = [1, 2, 4, 6, 8, 16, 32]

def stage_dir(base: Path, seg: int):
    """<base>/seg<seg>_from<prev>/run_<n> for whichever prev/run exists."""
    cands = sorted(base.glob(f'seg{seg}_from*/run_*'))
    return cands[0] if cands else None


def stage_weights(d: Path):
    """Best checkpoint's model.safetensors for a stage dir, or None if it saved
    nothing (stage stopped at step 0 by StopOnMetricValue)."""
    cks = sorted(d.glob('checkpoint-*'), key=lambda p: int(p.name.split('-')[1]))
    if not cks:
        return None
    ts = cks[-1] / 'trainer_state.json'
    if ts.exists():
        best = json.load(open(ts)).get('best_model_checkpoint')
        if best:
            # the recorded path is from the cluster job's filesystem; only the
            # checkpoint-XXX basename is meaningful here
            cand = d / Path(best).name / 'model.safetensors'
            if cand.exists():
                return cand
    return cks[-1] / 'model.safetensors'


def resolve(runs_root: Path):
    """-> list of dicts describing every variant that reached the seg32 stage."""
    out = []
    for task_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        for base in sorted(p for p in task_dir.iterdir() if p.is_dir()):
            present = {s: d for s in STAGES if (d := stage_dir(base, s)) is not None}
            if 32 not in present:
                continue
            # NOTE: no all_results.json gate here. Checkpoints copied down from
            # the cluster mid-run have checkpoint-XXX/ but no all_results.json,
            # and silently dropping them is what kept qa3 (and qa2 pool) out of
            # every eval. A saved checkpoint is the only thing we need; the
            # walk-back below picks the deepest stage that has one.
            cpt = src_stage = None
            zero_step = []
            for s in sorted(present, reverse=True):
                w = stage_weights(present[s])
                if w is not None:
                    cpt, src_stage = w, s
                    break
                zero_step.append(s)
            if cpt is None:
                continue
            out.append(dict(task=task_dir.name, run_name=base.name, base=base,
                            cpt=cpt, weights_stage=src_stage, zero_step_stages=zero_step,
                            cfg=json.load(open(present[32] / 'config.json'))['cli_args']))
    return out


def eval_cmd(v, n_segments, exp_path, batch_size, parallel_prefill, stream_logits,
             last_segment_only, efficient, workers, python):
    c = v['cfg']
    return [
        # same launcher as the babilong training runs and the babilong (v1) eval
        # scripts -- plain `python` would silently evaluate in fp32.
        str(Path(python).parent / 'accelerate'), 'launch',
        '--main_process_port', '0',
        '--num_processes', '1',
        '--mixed_precision', 'bf16',
        '--config_file', 'accelerate.yaml',
        RUNNER,
        '--exp_path', str(exp_path),
        '--per_device_batch_size', str(batch_size),
        '--gradient_accumulation_steps', '1',
        '--total_batch_size', str(batch_size),
        '--babi_path', c['babi_path'],
        '--task_dataset', c['task_dataset'],
        '--noise_dataset', c['noise_dataset'],
        '--segment_size', str(c['segment_size']),
        '--max_n_segments', str(n_segments),
        '--vary_n_segments', 'False',
        '--model_cpt', str(v['cpt']),
        '--validate_only', 'True',
        '--pretrained_model', c['pretrained_model'],
        '--n_head', str(c['n_head']),
        '--fla_layer', c['fla_layer'],
        '--state_size', str(c['state_size']),
        '--expand_v', str(c['expand_v']),
        '--conv_kernel', str(c['conv_kernel']),
        '--num_memory_vectors', str(c['num_memory_vectors']),
        '--write_mode', c['write_mode'],
        '--read_mode', c['read_mode'],
        '--use_parallel_prefill', str(parallel_prefill),
        '--eval_stream_logits', str(stream_logits),
        '--eval_last_segment_only', str(last_segment_only),
        '--efficient_model', str(efficient),
        '--dataloader_num_workers', str(workers),
        '--max_steps', '1', '--warmup_steps', '0', '--eval_steps', '1', '--logging_steps', '1',
        '--metric_for_best_model', 'exact_match',
        '--seed', str(c['seed']),
    ]


def _free_mib(gpu):
    """(free GPU MiB on `gpu`, available host MiB)."""
    g = subprocess.check_output(
        ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits',
         '-i', str(gpu)], text=True).strip().splitlines()[0]
    h = 0
    for line in open('/proc/meminfo'):
        if line.startswith('MemAvailable:'):
            h = int(line.split()[1]) // 1024
            break
    return int(g), h


def wait_for_memory(gpu, need_gpu_mib, need_host_mib, poll=60, tries=120):
    """Block until the box has headroom. This machine is painful to reboot, so
    never start an eval into a nearly-full GPU or a nearly-full host."""
    for _ in range(tries):
        g, h = _free_mib(gpu)
        if g >= need_gpu_mib and h >= need_host_mib:
            return True, g, h
        print(f'  waiting for memory on gpu{gpu}: free={g} MiB (need {need_gpu_mib}), '
              f'host avail={h} MiB (need {need_host_mib})', flush=True)
        time.sleep(poll)
    return False, *_free_mib(gpu)


def run_one(job, args):
    """Run a single eval on its assigned GPU. Returns (exp_path, rc)."""
    v, n, gpu = job['v'], job['n'], job['gpu']
    exp_path = job['exp_path']
    ok, g, h = wait_for_memory(gpu, args.min_free_gpu_mib, args.min_avail_host_mib)
    if not ok:
        print(f'ABORT (no memory headroom): {exp_path}', flush=True)
        return str(exp_path), 99
    bs = args.big_batch_size if n >= args.big_threshold else args.batch_size
    cmd = eval_cmd(v, n, exp_path, bs, args.parallel_prefill, args.stream_logits,
                   args.last_segment_only, args.efficient, args.workers, args.python)
    print(f"\n=== EVAL gpu{gpu} {v['task']}/{v['run_name']} @ {n} segments "
          f"({n * v['cfg']['segment_size']} tokens), bs={bs}  "
          f"[gpu free {g} MiB, host avail {h} MiB]\n{' '.join(cmd)}", flush=True)
    if args.dry_run:
        return str(exp_path), 0
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(gpu))
    log = exp_path.parent / 'eval.log'
    exp_path.mkdir(parents=True, exist_ok=True)
    with open(log, 'w') as fh:
        rc = subprocess.call(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT)
    peak = ''
    try:
        import re as _re
        txt = open(log).read()
        m = _re.findall(r"'eval_runtime': ([0-9.]+)", txt)
        if m:
            peak = f'  runtime={float(m[-1]):.0f}s'
        res = exp_path / 'all_results.json'
        if res.exists():
            d = json.load(open(res))
            peak += (f"  em={d.get('eval_exact_match')}"
                     f"  gpu_peak={d.get('peak_gpu_alloc_mib')}MiB"
                     f"  gpu_reserved={d.get('peak_gpu_reserved_mib')}MiB"
                     f"  host_rss={d.get('peak_host_rss_mib')}MiB")
    except Exception:
        pass
    print(f'  -> rc={rc}{peak}  {exp_path}', flush=True)
    return str(exp_path), rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs-root', default='runs-rmmv5p7/babilong2')
    ap.add_argument('--tasks', nargs='*', default=None, help='qa1 qa2 ... (default: all)')
    ap.add_argument('--variants', nargs='*', default=None, help='substrings matched against run_name')
    ap.add_argument('--eval-segments', nargs='*', type=int, default=DEFAULT_EVAL_SEGMENTS)
    ap.add_argument('--batch-size', type=int, default=8)
    ap.add_argument('--big-batch-size', type=int, default=2, help='batch size at >= --big-threshold segments')
    ap.add_argument('--big-threshold', type=int, default=128)
    ap.add_argument('--parallel-prefill', default='False',
                    help='recurrent (False) is bit-equivalent and the only thing that fits at >=256 segments')
    ap.add_argument('--stream-logits', default='True')
    ap.add_argument('--python', default=os.environ.get('BABILONG_PYTHON', sys.executable))
    ap.add_argument('--list', action='store_true', help='print the resolved variants and exit')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--last-segment-only', default='True',
                    help='constant-memory eval: keep only the final segment of labels/preds')
    ap.add_argument('--gpus', nargs='*', type=int, default=[0],
                    help='GPU pool; one eval per GPU at a time')
    ap.add_argument('--min-free-gpu-mib', type=int, default=20000)
    ap.add_argument('--min-avail-host-mib', type=int, default=20000)
    ap.add_argument('--efficient', default='True',
                    help='use modeling_rmt/huggingface_rmm_v5p7_eff (equivalence-tested)')
    ap.add_argument('--workers', type=int, default=1, help='dataloader workers per eval')
    # Several variants' seg32 stage halted at step 0 (first eval already hit
    # exact_match 1.0), so their weights really come from seg6/seg8/seg16.
    # Extrapolating a 3K-context model to 512K is pure waste, so gate the long
    # lengths on how deep the model was ACTUALLY trained.
    ap.add_argument('--exp-suffix', default='',
                    help="appended to the eval dir name, e.g. '_bs1' -> "
                         "eval_seg<N>_from32_bs1/run_1. Lets a second batch-size "
                         "sweep live beside the first instead of overwriting it.")
    ap.add_argument('--min-weights-stage', type=int, default=1,
                    help='skip variants whose weights come from a curriculum stage below this')
    args = ap.parse_args()

    os.chdir(REPO_ROOT)
    runs_root = Path(args.runs_root)
    variants = resolve(runs_root)
    if args.tasks:
        variants = [v for v in variants if v['task'] in args.tasks]
    if args.variants:
        variants = [v for v in variants if any(s in v['run_name'] for s in args.variants)]
    if args.min_weights_stage > 1:
        kept = [v for v in variants if v['weights_stage'] >= args.min_weights_stage]
        for v in variants:
            if v not in kept:
                print(f"  skip (weights from seg{v['weights_stage']} < "
                      f"seg{args.min_weights_stage}): {v['task']}/{v['run_name']}")
        variants = kept

    print(f'{len(variants)} variant(s) reached the seg32 stage under {runs_root}:')
    for v in variants:
        zs = f" (stages {v['zero_step_stages']} trained 0 steps)" if v['zero_step_stages'] else ''
        print(f"  {v['task']}/{v['run_name']}\n"
              f"      weights <- seg{v['weights_stage']}: {v['cpt'].relative_to(runs_root)}{zs}")
    if args.list:
        return

    # SEGMENTS OUTER, with a barrier between lengths: every variant finishes
    # length N before any variant starts N+1. That ordering is the point -- the
    # long lengths are the expensive, risky ones, and we want a complete row at
    # each context length before committing to the next.
    failures = []
    for n in args.eval_segments:
        todo = []
        for v in variants:
            exp_path = v['base'] / f'eval_seg{n}_from32{args.exp_suffix}' / 'run_1'
            if (exp_path / 'all_results.json').exists():
                print(f'done, skip {exp_path}')
                continue
            todo.append(dict(v=v, n=n, exp_path=exp_path))
        if not todo:
            continue
        print(f'\n########## {n} segments ({n * 512} tokens): {len(todo)} eval(s) '
              f'on gpus {args.gpus} ##########', flush=True)
        # one job per GPU at a time
        with ThreadPoolExecutor(max_workers=len(args.gpus)) as pool:
            futs = []
            for i, job in enumerate(todo):
                job['gpu'] = args.gpus[i % len(args.gpus)]
                futs.append(pool.submit(run_one, job, args))
            for f in futs:
                path, rc = f.result()
                if rc != 0:
                    failures.append((path, rc))
        if failures:
            # a failure at length n means length 2n is very unlikely to fit
            print(f'\nstopping before longer lengths: {len(failures)} failure(s) at {n} segments',
                  flush=True)
            break

    if failures:
        print(f'\n{len(failures)} eval(s) failed:')
        for p, rc in failures:
            print(f'  rc={rc}  {p}')
        sys.exit(1)
    print('\nDone')


if __name__ == '__main__':
    main()
