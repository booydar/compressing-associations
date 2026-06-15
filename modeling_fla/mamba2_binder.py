"""Mamba2 with a swappable conv slot.

Subclasses ``fla.layers.mamba2.Mamba2`` and replaces the single ``nn.Conv1d``
(applied to the concatenated ``[B, C]`` tensor) with a ``Conv1dBinder``.

The fused CUDA path (``mamba_split_conv1d_scan_combined``) bakes the conv
into the SSM scan and can't be hooked, so for non-passthrough kinds we force
the unfused ``torch_forward`` path (which calls ``self.conv1d(...)`` as a
module — exactly the seam the binder needs).

See scripts/assoc-comp-fla-conv-study/STAGE3_SUBSTITUTION.md.
"""

from __future__ import annotations

import torch

from fla.layers.mamba2 import Mamba2
from fla.layers.utils import get_layer_cache, update_layer_cache

from .local_binder import Conv1dBinder


class Mamba2Binder(Mamba2):
    """Mamba2 with a configurable local binder in the conv slot."""

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

        if binder_kind != "passthrough":
            self.conv1d = Conv1dBinder(
                conv_dim=self.conv_dim, conv_kernel=self.conv_kernel_size,
                kind=binder_kind, fallback=self.conv1d,
                window=binder_window, n_heads=binder_n_heads, rank=binder_rank,
            )

    def forward(self, hidden_states: torch.Tensor, attention_mask=None,
                past_key_values=None, use_cache=False, output_attentions=False,
                **kwargs):
        if self.binder_kind == "passthrough":
            return super().forward(
                hidden_states, attention_mask=attention_mask,
                past_key_values=past_key_values, use_cache=use_cache,
                output_attentions=output_attentions, **kwargs,
            )
        # Force torch_forward so self.conv1d (= Conv1dBinder) is actually
        # called as a module. cuda_kernels_forward inlines the conv weights
        # into the SSM kernel and would bypass our hook.
        last_state = get_layer_cache(self, past_key_values)
        if (last_state is None and attention_mask is not None
                and attention_mask.shape[1] > 1 and attention_mask.shape[0] > 1):
            hidden_states = (hidden_states * attention_mask[:, :, None]).to(
                hidden_states.dtype
            )
        output, conv_state, ssm_state = self.torch_forward(
            hidden_states, last_state, use_cache, attention_mask,
        )
        update_layer_cache(
            self, past_key_values,
            recurrent_state=ssm_state, conv_state=conv_state,
            offset=hidden_states.shape[1],
        )
        return output, None, past_key_values
