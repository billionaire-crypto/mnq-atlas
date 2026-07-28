"""MNQ Empirical Market Atlas — a measurement instrument.

This package measures state validity, state prevalence, and conditional future-path
distributions. It does not search for strategies, rank cells by profitability, select a
"best" parameter, optimize stops or targets, compute expectancy or Sharpe, or emit any
currency figure. See REV6_FROZEN_SPEC.md §16.1.
"""

__all__ = ["SpineError"]


class SpineError(RuntimeError):
    """A fail-closed condition. Never caught to continue (spec §16.4.3)."""
