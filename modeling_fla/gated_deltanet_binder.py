"""GatedDeltaNet with a swappable conv slot.

Subclasses ``fla.layers.gated_deltanet.GatedDeltaNet`` and replaces the
three ``ShortConvolution`` modules (q / k / v conv1d) with ``LocalBinder``
instances. Forward inherits unchanged — the binder mimics
``ShortConvolution``'s call signature, so the parent code calls it without
modification.

See scripts/assoc-comp-fla-conv-study/STAGE3_SUBSTITUTION.md.
"""

from __future__ import annotations

import torch.nn as nn

from fla.layers.gated_deltanet import GatedDeltaNet

from .local_binder import ShortConvBinder


class GatedDeltaNetBinder(GatedDeltaNet):
    """GDN layer with a configurable local binder in the conv slot.

    Extra kwargs (all default to the no-op ``passthrough``):
        binder_kind   : passthrough | none | swa
        binder_window : sliding-window size (defaults to conv_size)
        binder_n_heads: SWA heads (default 1)
        binder_rank   : low-rank projection dim for SWA (default None)
    """

    def __init__(self, *args,
                 binder_kind: str = "passthrough",
                 binder_window: int | None = None,
                 binder_n_heads: int = 1,
                 binder_rank: int | None = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.binder_kind = binder_kind
        self.binder_window = binder_window
        self.binder_n_heads = binder_n_heads
        self.binder_rank = binder_rank

        if not self.use_short_conv:
            return

        def _wrap(orig: nn.Module, hidden: int) -> ShortConvBinder:
            return ShortConvBinder(
                hidden_size=hidden, conv_size=self.conv_size,
                kind=binder_kind, fallback=orig,
                window=binder_window, n_heads=binder_n_heads, rank=binder_rank,
                activation="silu",   # ShortConvolution(activation='silu')
            )

        self.q_conv1d = _wrap(self.q_conv1d, self.key_dim)
        self.k_conv1d = _wrap(self.k_conv1d, self.key_dim)
        self.v_conv1d = _wrap(self.v_conv1d, self.value_dim)
