"""FlashRNN-backed models for causal language modeling.

Wraps the flashrnn functional API into nn.Module classes compatible
with HuggingFace Trainer.
"""

import torch
import torch.nn as nn
from transformers import PretrainedConfig
from transformers.modeling_outputs import CausalLMOutput

from flashrnn import flashrnn, FlashRNNConfig

# gate counts per function type: (num_gates_w, num_gates_r, num_gates_t, num_states)
FLASHRNN_GATE_INFO = {
    "lstm":  (4, 4, 4, 2),
    "slstm": (4, 4, 4, 4),
    "gru":   (3, 3, 4, 1),
    "elman": (1, 1, 1, 1),
}

# Available base_model names -> flashrnn function name
FLASHRNN_MODELS = {
    "flashrnn_lstm":  "lstm",
    "flashrnn_gru":   "gru",
    "flashrnn_elman": "elman",
    "flashrnn_slstm": "slstm",
}


class FlashRNNLayer(nn.Module):
    """Single flashrnn layer with learnable input projection, recurrent weight, and bias."""

    def __init__(self, input_size, hidden_size, num_heads=1,
                 function="lstm", backend="cuda_fused", dtype_str="bfloat16",
                 forget_bias=1.0):
        super().__init__()
        assert hidden_size % num_heads == 0, \
            f"hidden_size ({hidden_size}) must be divisible by num_heads ({num_heads})"

        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = hidden_size // num_heads
        self.function = function
        self.backend = backend
        self.dtype_str = dtype_str

        gate_info = FLASHRNN_GATE_INFO[function]
        self.num_gates_w, self.num_gates_r, self.num_gates_t, self.num_states = gate_info

        # Input projection: input_size -> num_gates_w * hidden_size
        self.W = nn.Linear(input_size, self.num_gates_w * hidden_size)

        # Recurrent weight: [num_gates_r, num_heads, head_dim, head_dim]
        self.R = nn.Parameter(torch.empty(self.num_gates_r, num_heads, self.head_dim, self.head_dim))

        # Bias: [num_gates_t, num_heads, head_dim]
        self.b = nn.Parameter(torch.zeros(self.num_gates_t, num_heads, self.head_dim))

        self._init_parameters(forget_bias)

    def _init_parameters(self, forget_bias):
        # Orthogonal init for recurrent weight (per gate, per head)
        for g in range(self.num_gates_r):
            for h in range(self.num_heads):
                nn.init.orthogonal_(self.R.data[g, h])

        # Set forget gate bias for LSTM/sLSTM (gate index 1 is forget gate)
        if self.function in ("lstm", "slstm") and forget_bias != 0.0:
            with torch.no_grad():
                self.b.data[1].fill_(forget_bias)

    def forward(self, x):
        B, T, _ = x.shape
        Wx = self.W(x).view(B, T, self.num_gates_w, self.num_heads, self.head_dim)
        states, _ = flashrnn(Wx, self.R, self.b,
                             function=self.function,
                             backend=self.backend,
                            #  dtype=self.dtype_str
                             dtype="float32"
                             )
        # states shape: [num_states, B, T, num_heads, head_dim]
        # Always take state index 0 (h for LSTM, y for sLSTM, h for GRU/Elman)
        h = states[0].reshape(B, T, self.hidden_size)
        return h


class FlashRNNForCausalLM(nn.Module):
    """FlashRNN-based causal language model compatible with HuggingFace Trainer."""

    def __init__(self, vocab_size, hidden_size, num_layers, num_heads=1,
                 function="lstm", backend="cuda_fused", dtype_str="bfloat16",
                 pad_token_id=None):
        super().__init__()

        self.embedding = nn.Embedding(vocab_size, hidden_size, padding_idx=pad_token_id)
        self.layers = nn.ModuleList([
            FlashRNNLayer(
                input_size=hidden_size,
                hidden_size=hidden_size,
                num_heads=num_heads,
                function=function,
                backend=backend,
                dtype_str=dtype_str,
            )
            for _ in range(num_layers)
        ])
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)

        # Config object for HF Trainer compatibility (needs to_json_string, etc.)
        self.config = PretrainedConfig(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            function=function,
            backend=backend,
            model_type=f"flashrnn_{function}",
        )
        self.config.use_cache = False

    @property
    def dtype(self):
        return next(self.parameters()).dtype

    def forward(self, input_ids, labels=None, **kwargs):
        h = self.embedding(input_ids)
        for layer in self.layers:
            h = layer(h)
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
