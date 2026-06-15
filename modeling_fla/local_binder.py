"""LocalBinder — the conv-slot substitution module.

Replaces the depthwise causal conv in FLA's GatedDeltaNet / Mamba2 blocks
with a configurable local-mixing operator. Variants:

    passthrough : delegate to the original conv module unchanged (sanity).
    none        : identity (with the same external activation the conv has).
    swa         : causal sliding-window self-attention, window=W.

See scripts/assoc-comp-fla-conv-study/STAGE3_SUBSTITUTION.md.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


def _act_fn(name: str | None):
    if name in (None, "identity", "none"):
        return lambda x: x
    if name == "silu" or name == "swish":
        return F.silu
    if name == "gelu":
        return F.gelu
    raise ValueError(f"unknown activation: {name}")


class _SWA(nn.Module):
    """Causal sliding-window self-attention. Naive PyTorch impl — fine at
    the small seq-lens these experiments use (≤ a few hundred tokens). For
    longer contexts swap in flash_attn with window_size=(W-1, 0).
    """

    def __init__(self, hidden_size: int, window: int, n_heads: int = 1,
                 rank: int | None = None):
        super().__init__()
        self.hidden_size = hidden_size
        self.window = int(window)
        self.n_heads = int(n_heads)
        self.rank = rank

        inner = rank if rank is not None else hidden_size
        if rank is not None:
            self.down = nn.Linear(hidden_size, inner, bias=False)
            self.up = nn.Linear(inner, hidden_size, bias=False)
        else:
            self.down = self.up = None
        assert inner % self.n_heads == 0, (
            f"swa inner dim {inner} not divisible by n_heads {self.n_heads}"
        )
        self.head_dim = inner // self.n_heads
        self.qkv = nn.Linear(inner, 3 * inner, bias=False)
        self.o_proj = nn.Linear(inner, inner, bias=False)
        self.scale = self.head_dim ** -0.5

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x : [B, T, D]
        B, T, D = x.shape
        z = self.down(x) if self.down is not None else x
        d = z.shape[-1]

        qkv = self.qkv(z).reshape(B, T, 3, self.n_heads, self.head_dim)
        q, k, v = qkv.unbind(dim=2)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale  # [B,H,T,T]
        idx = torch.arange(T, device=x.device)
        causal = idx[None, :] <= idx[:, None]
        windowed = idx[None, :] > (idx[:, None] - self.window)
        mask = causal & windowed
        scores = scores.masked_fill(~mask, float("-inf"))
        attn = scores.softmax(dim=-1)
        # Rows that have no valid keys (shouldn't happen for window >= 1 and
        # causal, since position t can always attend to itself) become NaN
        # after softmax of all -inf. Defensive nan→0.
        attn = torch.nan_to_num(attn, nan=0.0)

        out = torch.matmul(attn, v).transpose(1, 2).reshape(B, T, d)
        out = self.o_proj(out)
        if self.up is not None:
            out = self.up(out)
        return out


class LocalBinderCore(nn.Module):
    """Pure [B, T, D] -> [B, T, D] mixing op. Activation is applied here so
    callers can wire it in place of an activation-fused conv (GDN's
    ShortConvolution) or an activation-followed conv (Mamba2's nn.Conv1d) by
    setting `activation` appropriately.
    """

    def __init__(self, hidden_size: int, kind: str, window: int,
                 n_heads: int = 1, rank: int | None = None,
                 activation: str | None = None):
        super().__init__()
        self.kind = kind
        self.activation = activation
        self._act = _act_fn(activation)
        if kind == "none":
            self.op = nn.Identity()
        elif kind == "swa":
            self.op = _SWA(hidden_size, window=window, n_heads=n_heads, rank=rank)
        else:
            raise ValueError(f"LocalBinderCore: unknown kind {kind!r}")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self._act(self.op(x))


class ShortConvBinder(nn.Module):
    """Drop-in for ``fla.modules.ShortConvolution``.

    Matches the call signature
        ``binder(x=..., cache=..., output_final_state=..., cu_seqlens=...)
        -> (output, new_cache)``
    used inside GatedDeltaNet.

    For ``kind="passthrough"`` it forwards to the wrapped ``fallback``
    ShortConvolution module — the equivalence smoke test is then literally a
    parity check between calling ``fallback(...)`` directly and calling
    ``ShortConvBinder(kind="passthrough", fallback=fallback)(...)``.
    """

    def __init__(self, hidden_size: int, conv_size: int, *, kind: str,
                 fallback: nn.Module | None, window: int | None = None,
                 n_heads: int = 1, rank: int | None = None,
                 activation: str = "silu"):
        super().__init__()
        self.kind = kind
        self.conv_size = conv_size
        self.hidden_size = hidden_size

        if kind == "passthrough":
            assert fallback is not None, "passthrough requires fallback module"
            self.inner = fallback
        else:
            w = window if window is not None else conv_size
            self.core = LocalBinderCore(
                hidden_size=hidden_size, kind=kind, window=w,
                n_heads=n_heads, rank=rank, activation=activation,
            )

    def forward(self, x, cache=None, output_final_state: bool = False,
                cu_seqlens=None):
        if self.kind == "passthrough":
            return self.inner(
                x=x, cache=cache, output_final_state=output_final_state,
                cu_seqlens=cu_seqlens,
            )
        if cache is not None or output_final_state:
            # Training-only sweep; cache is unused. Fail loudly rather than
            # silently producing a bad state.
            raise NotImplementedError(
                "ShortConvBinder does not support conv-state caching "
                "for non-passthrough kinds."
            )
        return self.core(x), None


class Conv1dBinder(nn.Module):
    """Drop-in for ``nn.Conv1d`` as used in ``fla.layers.mamba2.Mamba2``.

    Input is ``[B, D, T]`` (channels-first, matching Conv1d). Output is
    ``[B, D, T]`` — Mamba2's torch path immediately crops with
    ``[..., :seq_len]`` and then transposes, so returning ``[B, D, T]``
    works without modification on the caller side.

    For ``kind="passthrough"`` we delegate to the original Conv1d so the
    layer is bit-identical to FLA Mamba2.
    """

    def __init__(self, conv_dim: int, conv_kernel: int, *, kind: str,
                 fallback: nn.Conv1d | None, window: int | None = None,
                 n_heads: int = 1, rank: int | None = None):
        super().__init__()
        self.kind = kind
        self.conv_dim = conv_dim
        self.conv_kernel_size = conv_kernel

        if kind == "passthrough":
            assert isinstance(fallback, nn.Conv1d)
            self.inner = fallback
        else:
            w = window if window is not None else conv_kernel
            # Mamba2 applies the activation *outside* this module (in
            # torch_forward), so the binder should NOT apply silu itself.
            self.core = LocalBinderCore(
                hidden_size=conv_dim, kind=kind, window=w,
                n_heads=n_heads, rank=rank, activation=None,
            )
            # Mamba2's cuda_kernels_forward reaches into .weight / .bias.
            # We disable that path in Mamba2Binder.forward, but exposing
            # these attrs keeps any incidental access from blowing up.
            self.weight = fallback.weight if fallback is not None else None
            self.bias = fallback.bias if fallback is not None else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x : [B, D, T]
        if self.kind == "passthrough":
            return self.inner(x)
        y = self.core(x.transpose(1, 2))  # [B, T, D]
        return y.transpose(1, 2)
