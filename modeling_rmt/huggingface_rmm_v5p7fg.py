"""v5p7fg: v5p7 + write-gate/store collapse fix ("fg" = fix-gate). NO other changes.

DIAGNOSIS (probed 2026-07-17 on the N32 kv-retrieval runs): in v5p7 identity
mode the memory is a pure residual add-on (out_h = post_attn + GDN(LN_f(post_attn))),
so the GDN branch can be suppressed without breaking the local (attention+MLP)
paths. Ablations show the ENTIRE task lives in layer 0's GDN store (kill L0 ->
EM 0.947->0.000; kill L1-3 -> no change): L0 is the only layer whose
representations are consistent between the long context pass and the short QT
pass, hence the only usable store. The un-fixed model dies when L0 stops being
a store, and there are (empirically observed) TWO ways to die:

  (a) write-gate death: beta_L0 = sigmoid(b_proj) -> ~0.01 (seed 144 baseline;
      recurred under fix-v1 at lr5e-5 — the weights simply cancelled a +2 bias
      init, and a weak diluted penalty could not stop the slide before sigmoid
      saturation);
  (b) retention death: beta_L0 stays healthy but the decay gate alpha_L0
      collapses (0.44/token at 50k under fix-v1 at lr1e-4) so the store forgets
      within ~10 tokens, while the model parks an (unreadable) alpha=1 store at
      L2 -> v1=v2=0.

FIX v2 — a targeted STORE FLOOR on the store layer (default: layer 0), applied
as training-time hinge penalties on the TOP QUANTILE of each gate:

    beta hinge:  beta_floor_coef  * relu(beta_floor_tau  - mean(top beta_floor_frac  of beta))
    alpha hinge: alpha_floor_coef * relu(alpha_floor_tau - mean(top alpha_floor_frac of alpha))

  with alpha = exp(-exp(A_log) * softplus(a_proj(x) + dt_bias)) — the same
  per-token decay FLA computes in-kernel. Defaults: beta tau=0.2, alpha
  tau=0.98, frac=0.1, coef=20.0 each; coef=0 disables either.

  Design constraints honoured:
  - NOT a per-token floor: any individual token may still have beta=0
    (distractor filtering preserved) and fast decay (forgetting preserved);
    only "no token writes / nothing is retained" on the store layer is
    penalized. At a healthy store the hinges are exactly 0 and the objective
    is identical to v5p7.
  - Only the store layer (config.store_layer, default 0) is constrained; all
    other layers' gates are completely free (they may become pure filters or
    die — the ablation shows they are unused anyway). store_layer=-1 applies
    the floors to every layer (not recommended: fix-v1 showed the model then
    parks the store at a deep, unreadable layer).
  - Penalty gradients reach b_proj / a_proj / A_log / dt_bias DIRECTLY,
    independent of the (initially useless) retrieval read path — this is the
    escape route the self-sealing minimum lacks.

  b_proj is replaced with a bias=True copy (bias init = gate_bias_init,
  default 0.0 -> beta0 ~ 0.5, i.e. neutral start; the bias is kept as a
  single-scalar recovery lever for the penalty). fix-v1's aggressive +2.0 init
  is NOT default anymore: it delayed N16 take-off by ~30k steps and failed to
  prevent (a) anyway.

Everything else (formulas, parallel prefill, masks, caches) is inherited from
huggingface_rmm_v5p7 unmodified; parallel==recurrent equivalence is preserved
(the fix changes only b_proj init and adds training-only loss terms).
"""
from __future__ import annotations

import inspect

import torch
import torch.nn as nn
import torch.nn.functional as F

import fla.layers

from modeling_rmt.huggingface_rmm_v5p7 import (
    RecurrentMemoryBase,
    RecurrentMemoryCell,
    RecurrentMemoryConfig,
    RecurrentMemoryLayerWrapper,
    RecurrentMemoryWrapperBase,
)


class FGRecurrentMemoryConfig(RecurrentMemoryConfig):
    model_type = "rmm_fg"

    def __init__(self, gate_bias_init=0.0, store_layer=0,
                 beta_floor_tau=0.2, beta_floor_frac=0.1, beta_floor_coef=20.0,
                 alpha_floor_tau=0.98, alpha_floor_frac=0.1, alpha_floor_coef=20.0,
                 **kwargs):
        super().__init__(**kwargs)
        self.gate_bias_init = gate_bias_init
        self.store_layer = store_layer
        self.beta_floor_tau = beta_floor_tau
        self.beta_floor_frac = beta_floor_frac
        self.beta_floor_coef = beta_floor_coef
        self.alpha_floor_tau = alpha_floor_tau
        self.alpha_floor_frac = alpha_floor_frac
        self.alpha_floor_coef = alpha_floor_coef


def _top_frac_mean(x, frac):
    flat = x.flatten()
    k = max(1, int(frac * flat.numel()))
    return flat.topk(k).values.mean()


class FGRecurrentMemoryLayerWrapper(RecurrentMemoryLayerWrapper):
    """v5p7 wrapper + store-floor penalties collected at every GDN call
    (active only when this layer is the designated store layer)."""

    def __init__(self, *args, store_floor=False,
                 beta_floor_tau=0.2, beta_floor_frac=0.1,
                 alpha_floor_tau=0.98, alpha_floor_frac=0.1, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_floor = store_floor
        self.beta_floor_tau = beta_floor_tau
        self.beta_floor_frac = beta_floor_frac
        self.alpha_floor_tau = alpha_floor_tau
        self.alpha_floor_frac = alpha_floor_frac
        self._store_penalties = []   # list of (beta_pen, alpha_pen)

    def _gdn(self, x_norm):
        if self.training and self.store_floor:
            fl = self.fla_layer
            beta_pen = alpha_pen = None
            if self.beta_floor_tau > 0:
                # Same quantity FLA computes in forward: beta = sigmoid(b_proj(x)).
                beta = fl.b_proj(x_norm).float().sigmoid()
                beta_pen = torch.relu(self.beta_floor_tau
                                      - _top_frac_mean(beta, self.beta_floor_frac))
            if self.alpha_floor_tau > 0:
                # Same per-token decay FLA computes in-kernel:
                # alpha = exp(-exp(A_log) * softplus(a_proj(x) + dt_bias)).
                g = -fl.A_log.float().exp() * F.softplus(
                    fl.a_proj(x_norm).float() + fl.dt_bias.float())
                alpha = g.exp()
                alpha_pen = torch.relu(self.alpha_floor_tau
                                       - _top_frac_mean(alpha, self.alpha_floor_frac))
            if beta_pen is not None or alpha_pen is not None:
                self._store_penalties.append((beta_pen, alpha_pen))
        return super()._gdn(x_norm)

    def pop_store_penalties(self):
        pens, self._store_penalties = self._store_penalties, []
        return pens


class FGRecurrentMemoryCell(RecurrentMemoryCell):
    """Same wrapping as v5p7's cell, but uses FGRecurrentMemoryLayerWrapper,
    gives each GDN's b_proj a bias term, and marks the store layer."""

    def __init__(self, base_model, fla_layer_name="GatedDeltaNet",
                 num_memory_vectors=1, write_mode='cross_attn',
                 read_mode='cross_attn', write_value_dim=None,
                 num_memory_heads=1, gate_bias_init=0.0, store_layer=0,
                 beta_floor_tau=0.2, beta_floor_frac=0.1,
                 alpha_floor_tau=0.98, alpha_floor_frac=0.1,
                 **fla_layer_kwargs):
        nn.Module.__init__(self)
        self.model = base_model

        model_hidden_size = getattr(base_model.config, "n_embd",
                                    getattr(base_model.config, "hidden_size", None))
        identity = (write_mode == 'identity')
        gdn_hidden_size = model_hidden_size if identity else (write_value_dim or model_hidden_size)
        model_dtype = next(base_model.parameters()).dtype
        model_device = next(base_model.parameters()).device

        layer_cls = getattr(fla.layers, fla_layer_name)
        sig = inspect.signature(layer_cls.__init__)
        excluded = {"self", "hidden_size", "layer_idx"}
        filtered_kwargs = {
            k: v for k, v in fla_layer_kwargs.items()
            if k in sig.parameters and k not in excluded
        }

        transformer_layers = self._get_transformer_layers(base_model)
        for i, layer in enumerate(transformer_layers):
            fla_layer = layer_cls(
                hidden_size=gdn_hidden_size,
                layer_idx=0,
                **filtered_kwargs,
            ).to(dtype=model_dtype, device=model_device)

            # bias=True b_proj: neutral init by default (beta0 ~ 0.5), the bias
            # is a single-scalar recovery lever for the store-floor penalty.
            old = fla_layer.b_proj
            b_proj = nn.Linear(old.in_features, old.out_features, bias=True)
            with torch.no_grad():
                b_proj.weight.copy_(old.weight)
                b_proj.bias.fill_(float(gate_bias_init))
            fla_layer.b_proj = b_proj.to(dtype=model_dtype, device=model_device)

            wrapped = FGRecurrentMemoryLayerWrapper(
                base_layer=layer.to(dtype=model_dtype, device=model_device),
                fla_layer=fla_layer,
                model_hidden_size=model_hidden_size,
                num_memory_vectors=num_memory_vectors,
                write_mode=write_mode,
                read_mode=read_mode,
                write_value_dim=write_value_dim,
                num_memory_heads=num_memory_heads,
                store_floor=(store_layer < 0 or i == store_layer),
                beta_floor_tau=beta_floor_tau,
                beta_floor_frac=beta_floor_frac,
                alpha_floor_tau=alpha_floor_tau,
                alpha_floor_frac=alpha_floor_frac,
            )
            transformer_layers[i] = wrapped

        self._mask_cache = {}


class FGRecurrentMemoryWrapperBase(RecurrentMemoryWrapperBase):
    def __init__(self, memory_cell, beta_floor_coef=20.0, alpha_floor_coef=20.0,
                 **rmt_kwargs):
        super().__init__(memory_cell, **rmt_kwargs)
        self.beta_floor_coef = beta_floor_coef
        self.alpha_floor_coef = alpha_floor_coef

    def process_outputs(self, cell_outputs, **kwargs):
        out = super().process_outputs(cell_outputs, **kwargs)
        layers = RecurrentMemoryCell._get_transformer_layers(self.memory_cell.model)
        beta_pens, alpha_pens = [], []
        for layer in layers:
            if hasattr(layer, 'pop_store_penalties'):
                for bp, ap in layer.pop_store_penalties():
                    if bp is not None:
                        beta_pens.append(bp)
                    if ap is not None:
                        alpha_pens.append(ap)
        if self.training and kwargs.get("labels") is not None:
            if beta_pens and self.beta_floor_coef > 0:
                out["loss"] = out["loss"] + self.beta_floor_coef * torch.stack(beta_pens).sum()
            if alpha_pens and self.alpha_floor_coef > 0:
                out["loss"] = out["loss"] + self.alpha_floor_coef * torch.stack(alpha_pens).sum()
        return out


class FGRecurrentMemoryBase(RecurrentMemoryBase):
    config_class = FGRecurrentMemoryConfig

    def __init__(self, config: FGRecurrentMemoryConfig, **kwargs):
        super(RecurrentMemoryBase, self).__init__(config, **kwargs)
        from transformers import AutoConfig, AutoModelForCausalLM

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if config.from_pretrained:
            base_model = AutoModelForCausalLM.from_pretrained(
                config.from_pretrained,
                device_map="auto" if torch.cuda.is_available() else None,
            )
        else:
            base_config = (
                config.base_model_config
                if config.base_model_config is not None
                else AutoConfig.from_pretrained(config.base_model_name)
            )
            base_model = AutoModelForCausalLM.from_config(base_config).to(device)

        self.rmm_config = config
        memory_cell = FGRecurrentMemoryCell(
            base_model,
            fla_layer_name=config.fla_layer_name,
            num_memory_vectors=config.num_memory_vectors,
            write_mode=config.write_mode,
            read_mode=config.read_mode,
            write_value_dim=config.write_value_dim,
            num_memory_heads=config.num_memory_heads,
            gate_bias_init=config.gate_bias_init,
            store_layer=config.store_layer,
            beta_floor_tau=config.beta_floor_tau,
            beta_floor_frac=config.beta_floor_frac,
            alpha_floor_tau=config.alpha_floor_tau,
            alpha_floor_frac=config.alpha_floor_frac,
            **config.fla_layer_kwargs(),
        )
        self.rmt = FGRecurrentMemoryWrapperBase(
            memory_cell,
            beta_floor_coef=config.beta_floor_coef,
            alpha_floor_coef=config.alpha_floor_coef,
            use_parallel_prefill=getattr(config, 'use_parallel_prefill', True),
            max_n_segments=config.max_n_segments,
            think_token_id=config.think_token_id,
            answer_token_id=config.answer_token_id,
            bos_token_id=config.bos_token_id,
            eos_token_id=config.eos_token_id,
        )
