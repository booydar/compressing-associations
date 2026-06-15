"""Confirm v6p2's gap closes the conv read->write leak.

Same probe as conv_leak_probe.py (hold writes fixed, vary reads, measure the
resulting recurrent_state change), comparing two layouts on the SAME gdn:
  G=0  -> [reads, writes]            (v6p0): expect non-zero leak
  G=5  -> [reads, gap(zeros), writes] (v6p2, gap=conv_size+1): expect ~0
"""
import os, sys
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from modeling_rmt.huggingface_rmm_v6p2 import ReadAwareGatedDeltaNet
from fla.models.utils import Cache

DEVICE = "cuda"
HIDDEN, HEAD_DIM, NUM_HEADS, CONV = 128, 8, 4, 4
T, B = 7, 4
GAP = CONV + 1   # v6p2 default


def build(seed=0):
    torch.manual_seed(seed)
    return ReadAwareGatedDeltaNet(
        hidden_size=HIDDEN, expand_v=2.0, head_dim=HEAD_DIM, num_heads=NUM_HEADS,
        use_short_conv=True, conv_size=CONV, layer_idx=0).to(DEVICE).eval()


def state(gdn, reads, writes, G):
    T_, M = reads.shape[1], writes.shape[1]
    if G > 0:
        gap = reads.new_zeros(B, G, reads.shape[-1])
        x = torch.cat([reads, gap, writes], dim=1)
        n_valved = T_ + G
    else:
        x = torch.cat([reads, writes], dim=1)
        n_valved = T_
    m = torch.cat([torch.ones(n_valved, dtype=torch.bool, device=DEVICE),
                   torch.zeros(M, dtype=torch.bool, device=DEVICE)]).unsqueeze(0).expand(B, -1)
    out = gdn(x, attention_mask=None, past_key_values=Cache(), use_cache=True, read_mask=m)
    return out[2][0]["recurrent_state"]


print(f"gap={GAP} (conv_size={CONV})")
print(f"{'M':>3} | {'G=0 leak (v6p0)':>16} {'rel':>7} | {'G=%d (v6p2)':>16} {'rel':>9}" % GAP)
print("-" * 60)
for M in (1, 2, 3, 4, 8):
    gdn = build()
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    rA = torch.randn(B, T, HIDDEN, device=DEVICE)
    rB = torch.randn(B, T, HIDDEN, device=DEVICE)
    for G, store in ((0, "d0"), (GAP, "dg")):
        SA, SB = state(gdn, rA, writes, G), state(gdn, rB, writes, G)
        d = (SA - SB).abs().max().item()
        r = d / SA.abs().max().item()
        locals()[store] = (d, r)
    print(f"{M:>3} | {d0[0]:>16.3e} {d0[1]:>6.1%} | {dg[0]:>16.3e} {dg[1]:>8.2%}")

print("\nG=0 leaks (reads change the state); G=%d -> ~0 (state is now a pure "
      "function of the compressed writes)." % GAP)
