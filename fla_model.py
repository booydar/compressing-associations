"""FLA-backed models for causal language modeling.

Wraps flash-linear-attention layers (fla.layers) into an nn.Module
compatible with HuggingFace Trainer.
"""

import inspect

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
        layer_signature = inspect.signature(layer_cls.__init__)
        shared_layer_kwargs = {
            "hidden_size": hidden_size,
            "layer_idx": 0,
            **layer_kwargs,
        }
        if "num_heads" in layer_signature.parameters:
            shared_layer_kwargs["num_heads"] = num_heads
            if num_heads != 1:
                raise NotImplementedError(f"num_heads != 1 is not supported for {layer_type}")
        if "head_dim" in layer_signature.parameters and "head_dim" not in shared_layer_kwargs:
            expand = shared_layer_kwargs.get("expand", None)
            if expand is None:
                # Fall back to the layer's own default for expand
                expand_param = layer_signature.parameters.get("expand", None)
                if expand_param is not None and expand_param.default is not inspect.Parameter.empty:
                    expand = expand_param.default
            if expand is not None:
                intermediate_size = int(expand * hidden_size)
                shared_layer_kwargs["head_dim"] = intermediate_size // num_heads
            else:
                shared_layer_kwargs["head_dim"] = hidden_size // num_heads
        shared_layer_kwargs.pop("layer_idx")

        self.embedding = nn.Embedding(vocab_size, hidden_size, padding_idx=pad_token_id)
        self.layers = nn.ModuleList([
            layer_cls(
                **shared_layer_kwargs,
                layer_idx=i,
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
            **layer_kwargs,
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
