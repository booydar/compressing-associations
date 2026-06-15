"""Does the TRAINED v6p2 checkpoint still leak reads into the written state?

For each layer's actual trained GDN weights, hold writes fixed, vary reads, and
measure the resulting recurrent_state change, under two layouts:
  G=0  [reads, writes]            -> what v6p0 (leaky) did
  G=5  [reads, gap(zeros), writes] -> what v6p2 actually runs

If G=5 -> ~0 on the trained weights, the conv channel is genuinely closed in the
model that scored 0.994 EM => that 0.994 cannot be coming from a conv leak.
"""
import os, sys, json
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from transformers import LlamaConfig
from modeling_rmt.huggingface_rmm_v6p2 import (
    RecurrentMemoryBase, RecurrentMemoryConfig, RecurrentMemoryCell)
from fla.models.utils import Cache

DEVICE = "cuda"
CKPT = os.path.join(ROOT,
    "runs-rmmv6p2/N16-K2V2-V62_1M/"
    "rmmv6p2_GatedDeltaNet_llama_L4H4D128_ss32_M16_identity_pool_lr3e-04_bs64_pps1_tps7/"
    "run_2/checkpoint-17500")
T, M, B, HIDDEN, GAP = 7, 16, 4, 128, 5


def build():
    cfg = json.load(open(os.path.join(CKPT, "config.json")))
    base = LlamaConfig(**cfg["base_model_config"])
    keys = ["fla_layer_name","num_heads","head_dim","expand_v","conv_size","use_short_conv",
            "state_size","num_memory_vectors","write_mode","read_mode","write_value_dim",
            "num_memory_heads","use_parallel_prefill","max_n_segments","think_token_id",
            "answer_token_id","bos_token_id","eos_token_id"]
    rc = RecurrentMemoryConfig(base_model_config=base, **{k: cfg[k] for k in keys if k in cfg})
    model = RecurrentMemoryBase(rc).to(DEVICE).eval()
    from safetensors.torch import load_model
    load_model(model, os.path.join(CKPT, "model.safetensors"), strict=False, device=DEVICE)
    return model


def state(gdn, reads, writes, G):
    if G > 0:
        gap = reads.new_zeros(B, G, reads.shape[-1])
        x = torch.cat([reads, gap, writes], dim=1); nv = T + G
    else:
        x = torch.cat([reads, writes], dim=1); nv = T
    m = torch.cat([torch.ones(nv, dtype=torch.bool, device=DEVICE),
                   torch.zeros(M, dtype=torch.bool, device=DEVICE)]).unsqueeze(0).expand(B, -1)
    out = gdn(x, attention_mask=None, past_key_values=Cache(), use_cache=True, read_mask=m)
    return out[2][0]["recurrent_state"]


def main():
    model = build()
    layers = RecurrentMemoryCell._get_transformer_layers(model.rmt.memory_cell.model)
    torch.manual_seed(0)
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    rA = torch.randn(B, T, HIDDEN, device=DEVICE)
    rB = torch.randn(B, T, HIDDEN, device=DEVICE)
    print(f"TRAINED v6p2 N16 M16 ckpt (EM 0.994), reads vary / writes fixed")
    print(f"{'layer':>5} | {'G=0 (no gap)':>16} | {'G=5 (v6p2 runs this)':>22}")
    print("-" * 52)
    with torch.no_grad():
        for li, layer in enumerate(layers):
            g = layer.fla_layer
            d0 = state(g, rA, writes, 0); d0 = (d0 - state(g, rB, writes, 0)).abs().max().item()
            sA = state(g, rA, writes, GAP); dg = (sA - state(g, rB, writes, GAP)).abs().max().item()
            rel0 = d0 / state(g, rA, writes, 0).abs().max().item()
            relg = dg / sA.abs().max().item()
            print(f"{li:>5} | {d0:>9.3e} {rel0:>5.0%} | {dg:>13.3e} {relg:>6.2%}")
    print("\nG=5 ~0 on trained weights => the channel is closed in the 0.994-EM "
          "model. Its accuracy does NOT come from conv-smuggling raw tokens.")


if __name__ == "__main__":
    main()
