"""Build an FLA model with its conv slot swapped for a LocalBinder.

The cleanest way to thread the binder kwargs into FLA's HF model factory
without forking ``modeling_*.py`` files is to monkey-patch the layer class
in the modules where the block imports it ``from`` — for the lifetime of
the call only.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from .gated_deltanet_binder import GatedDeltaNetBinder
from .mamba2_binder import Mamba2Binder


@dataclass
class BinderConfig:
    kind: str = "passthrough"        # passthrough | none | swa
    window: int | None = None        # default = layer's conv_size
    n_heads: int = 1
    rank: int | None = None


# Module-level state read by the factory subclasses below. Set inside
# `patched_layers` only.
_BINDER_CFG: BinderConfig = BinderConfig()


def _factory(base_cls):
    """Build a subclass that fills in binder_* kwargs from the global cfg."""

    class _Factory(base_cls):
        def __init__(self, *args, **kwargs):
            cfg = _BINDER_CFG
            super().__init__(
                *args,
                binder_kind=cfg.kind,
                binder_window=cfg.window,
                binder_n_heads=cfg.n_heads,
                binder_rank=cfg.rank,
                **kwargs,
            )

    _Factory.__name__ = f"{base_cls.__name__}Factory"
    return _Factory


_GDNFactory = _factory(GatedDeltaNetBinder)
_M2Factory = _factory(Mamba2Binder)


@contextmanager
def patched_layers(binder: BinderConfig):
    """Swap GatedDeltaNet / Mamba2 with our binder factories for the
    duration of the ``with`` block. Restores originals on exit.
    """
    global _BINDER_CFG
    prev_cfg = _BINDER_CFG
    _BINDER_CFG = binder

    import fla.layers.gated_deltanet as _gdn_layer_mod
    import fla.layers.mamba2 as _m2_layer_mod

    targets = []  # list of (module, attr, original)
    # Original symbols in layer modules
    targets.append((_gdn_layer_mod, "GatedDeltaNet", _gdn_layer_mod.GatedDeltaNet))
    targets.append((_m2_layer_mod, "Mamba2", _m2_layer_mod.Mamba2))
    # The block constructors do `from fla.layers.X import Y` so the imported
    # symbol lives in the modeling module's namespace too — patch there.
    try:
        from fla.models.gated_deltanet import modeling_gated_deltanet as _gdn_modeling
        targets.append((_gdn_modeling, "GatedDeltaNet", _gdn_modeling.GatedDeltaNet))
    except ImportError:
        pass
    try:
        from fla.models.mamba2 import modeling_mamba2 as _m2_modeling
        targets.append((_m2_modeling, "Mamba2", _m2_modeling.Mamba2))
    except ImportError:
        pass

    for mod, attr, _orig in targets:
        new_cls = _GDNFactory if attr == "GatedDeltaNet" else _M2Factory
        setattr(mod, attr, new_cls)
    try:
        yield
    finally:
        for mod, attr, orig in targets:
            setattr(mod, attr, orig)
        _BINDER_CFG = prev_cfg


def build_fla_with_binder(cfg, binder: BinderConfig):
    """Construct an FLA model from ``cfg`` with the conv slot replaced.

    ``cfg`` is a fully-built FLA config (GatedDeltaNetConfig or Mamba2Config).
    """
    from transformers import AutoModelForCausalLM

    with patched_layers(binder):
        return AutoModelForCausalLM.from_config(cfg)
