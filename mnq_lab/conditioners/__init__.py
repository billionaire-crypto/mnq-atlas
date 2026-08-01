"""Phase 6 conditioner registry mechanics.

Actual conditioner calculations and assignments remain Phase 7.
"""

from mnq_lab.conditioners.registry import (
    CAUSAL_LABEL,
    DESCRIPTIVE_LABEL,
    ConditionerClass,
    ConditionerDescriptor,
    ConditionerRegistry,
    NegativeControl,
    NegativeControlFailure,
    RegisteredComparison,
    WitnessCheck,
    register_causal_conditioner,
    register_descriptive_conditioner,
)

__all__ = [
    "CAUSAL_LABEL",
    "DESCRIPTIVE_LABEL",
    "ConditionerClass",
    "ConditionerDescriptor",
    "ConditionerRegistry",
    "NegativeControl",
    "NegativeControlFailure",
    "RegisteredComparison",
    "WitnessCheck",
    "register_causal_conditioner",
    "register_descriptive_conditioner",
]
