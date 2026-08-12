"""Explicit deferred-null interfaces required by spec section 15 row 10."""

from __future__ import annotations

from dataclasses import dataclass

from mnq_lab import SpineError


class DeferredNullError(SpineError):
    """Raised when a descriptive-only null is requested as executable."""


@dataclass(frozen=True)
class DeferredNullInterface:
    name: str
    formal: bool = False
    p_value_available: bool = False

    def execute(self) -> None:
        raise DeferredNullError(
            f"{self.name} is descriptive only; its null generator is deferred"
        )


PHASE_GIVEN_VOL = DeferredNullInterface("phase_given_vol")
INTERACTION = DeferredNullInterface("interaction")
DEFERRED_NULLS = (PHASE_GIVEN_VOL, INTERACTION)
