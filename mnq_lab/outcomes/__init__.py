"""Outcome-side machinery: windows, completion accounting, (later) excursions.

Modules here know market mechanics — bars, RTH, horizons — but nothing about
studies (spec §16.3). They never read `data/locked_confirmation/`.
"""
