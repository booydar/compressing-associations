"""FLA-backed models for causal language modeling.

Wraps flash-linear-attention layers (fla.layers) into an nn.Module
compatible with HuggingFace Trainer.
"""

import torch
import torch.nn as nn
from transformers import PretrainedConfig
from transformers.modeling_outputs import CausalLMOutput

import fla.layers

FLA_MODELS = {
    "gated_delta_net": "GatedDeltaNet",
    "delta_net": "DeltaNet",
    "gla": "GatedLinearAttention",
    "linear_attention": "LinearAttention",
    "hgrn": "HGRNAttention",
    "hgrn2": "HGRN2Attention",
    "rwkv6": "RWKV6Attention",
    "rwkv7": "RWKV7Attention",
    "mamba": "Mamba",
    "mamba2": "Mamba2",
    "retention": "MultiScaleRetention",
}


class FLAForCausalLM(nn.Module):

    def __init__(self, vocab_size, hidden_size, num_layers, num_heads=4,
                 layer_type="GatedDeltaNet", pad_token_id=None, **layer_kwargs):
        super().__init__()

        layer_cls = getattr(fla.layers, layer_type)

        self.embedding = nn.Embedding(vocab_size, hidden_size, padding_idx=pad_token_id)
        self.layers = nn.ModuleList([
            layer_cls(
                hidden_size=hidden_size,
                num_heads=num_heads,
                layer_idx=i,
                **layer_kwargs,
            )
            for i in range(num_layers)
        ])
        self.norm = nn.RMSNorm(hidden_size)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)

        self.config = PretrainedConfig(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            layer_type=layer_type,
            model_type=f"fla_{layer_type}",
        )
        self.config.use_cache = False

    @property
    def dtype(self):
        return next(self.parameters()).dtype

    def forward(self, input_ids, labels=None, **kwargs):
        h = self.embedding(input_ids)
        for layer in self.layers:
            h = h + layer(h)[0]
        h = self.norm(h)
        logits = self.lm_head(h)

        loss = None
        if labels is not None:
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = nn.functional.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                ignore_index=-100,
            )

        return CausalLMOutput(loss=loss, logits=logits)
