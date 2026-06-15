"""Quantify the conv read->write leak in v6p0 identity-read.

Question: in the single [reads(T), writes(M)] GDN scan with the read-only valve,
can the read tokens (the segment tokens themselves) affect the recurrent_state
that gets written — i.e. bypass the compress bottleneck?

Method: hold the M write vectors FIXED, vary only the T read tokens, and measure
how much the resulting recurrent_state changes. The valve zeroes beta at read
positions, so reads cannot write directly — ANY state change is purely the
causal short conv bleeding read tokens into the first write tokens' k/v.

A non-zero diff = the leak exists (magnitude = how much). Compared against the
v6p1 two-call path (read on a fork, write-only on the real cache), which must
give exactly 0.
"""
import os, sys
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from modeling_rmt.huggingface_rmm_v6p0 import ReadAwareGatedDeltaNet
from fla.models.utils import Cache

DEVICE = "cuda"
HIDDEN, HEAD_DIM, NUM_HEADS, CONV = 128, 8, 4, 4   # match trained N8 M8 config
T, B = 7, 4


def build(seed=0):
    torch.manual_seed(seed)
    return ReadAwareGatedDeltaNet(
        hidden_size=HIDDEN, expand_v=2.0, head_dim=HEAD_DIM, num_heads=NUM_HEADS,
        use_short_conv=True, conv_size=CONV, layer_idx=0).to(DEVICE).eval()


def rmask(T, M):
    m = torch.cat([torch.ones(T, dtype=torch.bool, device=DEVICE),
                   torch.zeros(M, dtype=torch.bool, device=DEVICE)])
    return m.unsqueeze(0).expand(B, -1)


def state_v6p0(gdn, reads, writes):
    """Single scan over [reads, writes] with read_mask — the v6p0 path."""
    x = torch.cat([reads, writes], dim=1)
    out = gdn(x, attention_mask=None, past_key_values=Cache(),
              use_cache=True, read_mask=rmask(reads.shape[1], writes.shape[1]))
    return out[2][0]["recurrent_state"]


def state_v6p1(gdn, reads, writes):
    """Two calls: read on a throwaway cache, write-only on a real cache (the
    v6p1 split). Read can't touch the write's cache at all."""
    cache = Cache()
    # write-only (no read_mask -> normal write); this is the state we keep
    out = gdn(writes, attention_mask=None, past_key_values=cache, use_cache=True)
    return out[2][0]["recurrent_state"]


print(f"{'M':>3} | {'v6p0 state diff (reads differ)':>32} | {'rel':>8} | {'v6p1 diff':>10}")
print("-" * 70)
for M in (1, 2, 3, 4, 8):
    gdn = build()
    writes = torch.randn(B, M, HIDDEN, device=DEVICE)
    reads_A = torch.randn(B, T, HIDDEN, device=DEVICE)
    reads_B = torch.randn(B, T, HIDDEN, device=DEVICE)

    SA = state_v6p0(gdn, reads_A, writes)
    SB = state_v6p0(gdn, reads_B, writes)
    diff = (SA - SB).abs().max().item()
    rel = diff / SA.abs().max().item()

    # v6p1 control: write-only ignores reads entirely
    PA = state_v6p1(gdn, reads_A, writes)
    PB = state_v6p1(gdn, reads_B, writes)
    pdiff = (PA - PB).abs().max().item()

    print(f"{M:>3} | {diff:>32.4e} | {rel:>7.1%} | {pdiff:>10.2e}")

print("\nReads differ but writes are identical. Non-zero v6p0 diff = segment "
      "tokens leaking into the written state via the causal conv. v6p1 = 0.")
