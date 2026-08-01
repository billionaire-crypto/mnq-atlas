"""Phase 6 conditioner registry mechanics.

Actual conditioner calculations and assignments remain Phase 7.
"""

from mnq_lab.conditioners.registry import (
    DESCRIPTIVE_LABEL,
    ConditionerClass,
    ConditionerDescriptor,
    ConditionerRegistry,
    register_descriptive_conditioner,
)

__all__ = [
    "DESCRIPTIVE_LABEL",
    "ConditionerClass",
    "ConditionerDescriptor",
    "ConditionerRegistry",
    "register_descriptive_conditioner",
]
