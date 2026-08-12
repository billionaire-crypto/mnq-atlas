"""Frozen calibration entropy identity; this module runs no calibration."""

from __future__ import annotations

import hashlib
import struct

import numpy as np

from mnq_lab import SpineError

CALIBRATION_ROOT_LABEL = "MNQ ATLAS Phase 10 Test 9 randomized controls rev1"
CALIBRATION_ROOT_ENCODING = "UTF-8"
CALIBRATION_ROOT_SHA256 = (
    "05b25e58157921b96cd8f84fee78fe2a533f533fce496b4f72136412c55ac537"
)
CALIBRATION_ROOT_BYTE_ORDER = "big-endian"
CALIBRATION_ROOT_ENTROPY = (
    95_575_640,
    360_260_025,
    1_826_158_671,
    4_000_906_794,
    1_396_659_007,
    3_460_918_095,
    1_913_873_426,
    3_311_060_279,
)


def calibration_root_seed_sequence() -> np.random.SeedSequence:
    """Re-derive and return the immutable preregistered calibration root."""
    digest = hashlib.sha256(
        CALIBRATION_ROOT_LABEL.encode(CALIBRATION_ROOT_ENCODING)
    ).digest()
    derived_hex = digest.hex()
    derived_entropy = struct.unpack(">8I", digest)
    if CALIBRATION_ROOT_ENCODING != "UTF-8":
        raise SpineError("Phase 10 calibration root encoding differs")
    if CALIBRATION_ROOT_BYTE_ORDER != "big-endian":
        raise SpineError("Phase 10 calibration root byte order differs")
    if derived_hex != CALIBRATION_ROOT_SHA256:
        raise SpineError("Phase 10 calibration root digest differs")
    if derived_entropy != CALIBRATION_ROOT_ENTROPY:
        raise SpineError("Phase 10 calibration root entropy differs")
    return np.random.SeedSequence(CALIBRATION_ROOT_ENTROPY)
