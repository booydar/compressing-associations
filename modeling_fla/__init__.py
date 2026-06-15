"""Conv-substitution helpers for FLA's GatedDeltaNet and Mamba2 models.

Use :func:`build_fla_with_binder` to construct a stock FLA model whose conv
slot has been replaced by a ``LocalBinder``. Equivalent to calling
``AutoModelForCausalLM.from_config(cfg)`` with the layer class swapped.
"""

from .local_binder import (  # noqa: F401
    Conv1dBinder,
    LocalBinderCore,
    ShortConvBinder,
)
from .gated_deltanet_binder import GatedDeltaNetBinder  # noqa: F401
from .mamba2_binder import Mamba2Binder  # noqa: F401
from .build import build_fla_with_binder, BinderConfig  # noqa: F401
