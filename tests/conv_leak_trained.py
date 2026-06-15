"""Conv read->write leak measured on the TRAINED v6p0 identity_pool checkpoint.

Same probe as conv_leak_probe.py (hold writes fixed, vary reads, measure the
resulting recurrent_state change) but using each layer's actual trained GDN
weights instead of random init. Tells us whether the trained model learned to
suppress the read contamination or still folds raw segment tokens into memory.
"""
import os, sys, json
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from transformers import LlamaConfig
from modeling_rmt.huggingface_rmm_v6p0 import (
    RecurrentMemoryBase, RecurrentMemoryConfig, RecurrentMemoryCell,
)
from fla.models.utils import Cache

DEVICE = "cuda"
CKPT = os.path.join(
    ROOT,
    "runs-rmmv6p0/N8-K2V2-V62_1M/"
    "rmmv6p0_GatedDeltaNet_llama_L4H4D128_ss32_M8_identity_pool_lr3e-04_bs64_pps1_tps7/"
    "run_1/checkpoint-9500",
)
T, M, B, HIDDEN = 7, 8, 4, 128


def build_model():
    cfg = json.load(open(os.path.join(CKPT, "config.json")))
    base = LlamaConfig(**cfg["base_model_config"])
    rc = RecurrentMemoryConfig(
        base_model_config=base, fla_layer_name=cfg["fla_layer_name"],
        num_heads=cfg["num_heads"], head_dim=cfg["head_dim"], expand_v=cfg["expand_v"],
        conv_size=cfg["conv_size"], use_short_conv=cfg["use_short_conv"],
        state_size=cfg["state_size"], num_memory_vectors=cfg["num_memory_vectors"],
        write_mode=cfg["write_mode"], read_mode=cfg["read_mode"],
        write_value_dim=cfg["write_value_dim"], num_memory_heads=cfg["num_memory_heads"],
        use_parallel_prefill=cfg["use_parallel_prefill"], max_n_segments=cfg["max_n_segments"],
        think_token_id=cfg["think_token_id"], answer_token_id=cfg["answer_token_id"],
        bos_token_id=cfg["bos_token_id"], eos_token_id=cfg["eos_token_id"])
    model = RecurrentMemoryBase(rc).to(DEVICE).eval()
    from safetensors.torch import load_model
    load_model(model, os.path.join(CKPT, "model.safetensors"), strict=False, device=DEVICE)
    return model


def rmask(T, M):
    m = torch.cat([torch.ones(T, dtype=torch.bool, device=DEVICE),
                   torch.zeros(M, dtype=torch.bool, device=DEVICE)])
    return m.unsqueeze(0).expand(B, -1)


def state_v6p0(gdn, reads, writes):
    x = torch.cat([reads, writes], dim=1)
    out = gdn(x, attention_mask=None, past_key_values=Cache(),
              use_cache=True, read_mask=rmask(reads.shape[1], writes.shape[1]))
    return out[2][0]["recurrent_state"]


def main():
    if not torch.cuda.is_available():
        print("CUDA required."); return
    model = build_model()
    layers = RecurrentMemoryCell._get_transformer_layers(model.rmt.memory_cell.model)
    torch.manual_seed(0)
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    reads_A = torch.randn(B, T, HIDDEN, device=DEVICE)
    reads_B = torch.randn(B, T, HIDDEN, device=DEVICE)

    print(f"trained checkpoint, M={M} T={T}")
    print(f"{'layer':>5} | {'state diff (reads differ)':>26} | {'rel to |state|':>14}")
    print("-" * 54)
    with torch.no_grad():
        for li, layer in enumerate(layers):
            gdn = layer.fla_layer
            SA = state_v6p0(gdn, reads_A, writes)
            SB = state_v6p0(gdn, reads_B, writes)
            diff = (SA - SB).abs().max().item()
            rel = diff / SA.abs().max().item()
            print(f"{li:>5} | {diff:>26.4e} | {rel:>13.1%}")
    print("\nNon-zero = the TRAINED conv still folds raw read (segment) tokens "
          "into the written memory state, partly bypassing the compress.")


if __name__ == "__main__":
    main()
