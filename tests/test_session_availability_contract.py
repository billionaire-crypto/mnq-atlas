"""Pins the frozen session-availability v2 contract and its declared identities.

Written in the commit AFTER the contract, per the project's preregistration
pattern: a document cannot pin its own hash in the commit that creates it.

Each test states what breaks it, so none of them is a check that cannot fail.
"""

from __future__ import annotations

import hashlib

from mnq_lab.conditioners.artifacts import PHASE7_ARTIFACT_SCHEMA_VERSION
from mnq_lab.constants import REPO_ROOT
from mnq_lab.outcomes.artifacts import ARTIFACT_SCHEMA_VERSION
from mnq_lab.outcomes.excursions import OUTCOME_SCHEMA, OUTCOME_STATUSES
from mnq_lab.spine.accepted_calendar import CALENDAR_SHA256, CALENDAR_VERSION
from mnq_lab.spine.availability import (
    AVAILABILITY_CONTRACT_VERSION,
    EXCLUSION_REGISTRY_SHA256,
    EXCLUSION_REGISTRY_VERSION,
    UNAVAILABILITY_REASONS,
)
from mnq_lab.spine.session_quality import SESSION_QUALITY_STATUSES

CONTRACT = REPO_ROOT / "docs" / "SESSION_AVAILABILITY_V2_CONTRACT.md"
CONTRACT_BYTES = 14_345
CONTRACT_SHA256 = "fea24481eaf7b1d2d20b1da87d8ad0262f4284b0984ddd983f1b76ec2f3aa939"


def test_contract_raw_bytes_are_pinned():
    """Fails if the frozen contract is edited instead of superseded."""
    payload = CONTRACT.read_bytes()
    assert len(payload) == CONTRACT_BYTES
    assert hashlib.sha256(payload).hexdigest() == CONTRACT_SHA256
    assert b"\r" not in payload


def test_declared_identities_match_the_contract():
    """Fails if code and contract drift apart on any frozen identifier."""
    assert CALENDAR_VERSION == "mnq-cme-equity-index-calendar-v1"
    assert CALENDAR_SHA256 == (
        "b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069"
    )
    assert EXCLUSION_REGISTRY_VERSION == "mnq-session-exclusion-registry-v1"
    assert EXCLUSION_REGISTRY_SHA256 == (
        "0a37822f05a9bb895c8ac421c64bc1849b644985e5f6cd016658bbf479055e75"
    )
    assert AVAILABILITY_CONTRACT_VERSION == "session-availability-v1"
    assert ARTIFACT_SCHEMA_VERSION == "unit-o-outcomes-v2"
    assert PHASE7_ARTIFACT_SCHEMA_VERSION == "phase7-conditioner-artifacts-v2"


def test_frozen_vocabularies_and_precedence():
    """Fails if any closed vocabulary is reordered, extended or renamed."""
    assert OUTCOME_STATUSES == (
        "anchor_bar_missing",
        "structurally_unavailable",
        "path_timestamp_missing",
        "path_session_mismatch",
        "path_symbol_mismatch",
        "insufficient_components",
        "ok",
    )
    assert UNAVAILABILITY_REASONS == (
        "not_applicable",
        "no_scheduled_rth",
        "scheduled_close",
        "registered_interruption",
    )
    assert SESSION_QUALITY_STATUSES == (
        "excluded_unresolved_official_interruption",
        "no_scheduled_rth",
        "registered_structural_interruption",
        "observed_unexplained_mid_session_gap",
        "scheduled_early_close",
        "observed_unresolved_early_termination",
        "ok",
    )
    # the collapsing v1 label is retired and must not return
    assert "unresolved_truncated_session" not in SESSION_QUALITY_STATUSES
    assert "window_outside_rth" not in OUTCOME_STATUSES


def test_frozen_unit_o_schema_shape():
    """Fails if a column is added, removed or reordered without a new contract."""
    assert len(OUTCOME_SCHEMA) == 26
    assert OUTCOME_SCHEMA.index("structural_unavailability_reason") == (
        OUTCOME_SCHEMA.index("outcome_status") + 1
    )
    assert OUTCOME_SCHEMA[0] == "estimand"
    assert OUTCOME_SCHEMA[-1] == "outcome_valid"


def test_contract_states_the_binding_consumer_rule():
    """The section 5.1 rule is the one downstream code must obey.

    Fails if the rule is softened or removed: completion must use the fit
    predicate, never the status string.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    assert "window_fits_rth`, never `outcome_status`" in text
    assert "MUST NOT be rendered as a *cause*" in text
    assert "MUST NOT infer structural eligibility from the status string" in text


def test_contract_records_provenance_and_limitations():
    """Fails if the no-magnitude statement or the limitations are dropped."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "No tick, quantile, contrast, interval or any other outcome magnitude" in text
    assert "not established" in text and "proven absent" in text
    assert "There is no calendar v2." in text
    assert "There is no registered interruption input." in text
