"""Pins the frozen session-availability v2 contract and its declared identities.

Written in the commit AFTER the contract, per the project's preregistration
pattern: a document cannot pin its own hash in the commit that creates it.

Each test states what breaks it, so none of them is a check that cannot fail.
"""

from __future__ import annotations

import hashlib
import re

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
CONTRACT_BYTES = 19_419
CONTRACT_SHA256 = "5b2a77b38d6b68db1409822fec45f7f98cf92509d843bba156afba18bb1aff1b"


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
    assert "There is no calendar v2." in text
    assert "There is no registered interruption input." in text
    # equality-only conditioner comparison is declared, not smuggled
    assert "equality-only" in text


# --- F-A: semantic proof-of-absence detector --------------------------------
#
# Revision 1 pinned one exact negation clause and blocked five exact phrases.
# The Stage 6 audit showed a document could assert proof of absence in unlisted
# wordings ("demonstrated the absence", "proves no such boundary exists",
# "nonexistence is established", "shown to be absent") and still pass. This is
# the third attempt and it matches on affirmative LEMMAS rather than fixed
# phrases: a proof/certainty verb that governs an absence term inside one clause,
# with no nearby negation governing that verb. A parenthetical stitch keeps
# wording such as "demonstrates, beyond doubt, the absence" from evading the
# guard while unrelated comma-separated clauses remain independent.

# Verbs and adverbs that assert epistemic certainty of a conclusion.
_PROOF_LEMMA = re.compile(
    r"\b(?:prov(?:e|es|en|ed|ing)|proof|"
    r"demonstrat(?:e|es|ed|ing|ion|ions)|"
    r"establish(?:es|ed|ing)|"
    r"shows?|shown|"
    r"confirm(?:s|ed|ing)?|"
    r"conclusively|definitively|irrefutabl\w+|incontrovertibl\w+)\b",
    re.IGNORECASE,
)
# Terms asserting that something does not exist.
_ABSENCE_LEMMA = re.compile(
    r"\b(?:absence|absent|"
    r"nonexisten\w*|non-existen\w*|inexisten\w*|"
    r"no\s+such|"
    r"does\s+not\s+exist|do\s+not\s+exist|did\s+not\s+exist|"
    r"never\s+existed|not\s+to\s+exist|"
    r"no\s+\w+\s+exists?|"
    r"there\s+(?:is|was|are|were)\s+no|"
    r"none\b[^.;:\n]{0,80}\bexists?|"
    r"zero\s+\w+\s+existed)\b",
    re.IGNORECASE,
)
# A nearby negation before the proof verb turns the assertion into an honest
# denial ("not established", "never proven", "could not demonstrate"). The
# bounded window avoids treating an unrelated earlier negative statement as if
# it governed a later affirmative proof claim.
_GOVERNING_NEGATION = re.compile(
    r"\b(?:not|never|no|nor|cannot|neither|without|unable|fails?|failed)\b|n't",
    re.IGNORECASE,
)
_CLAUSE_SPLIT = re.compile(r"[.;:,\n]")
_SENTENCE_SPLIT = re.compile(r"[.;:\n]")
_NEGATION_WINDOW = 24


def _proof_of_absence_clauses(text: str) -> list[str]:
    """Return every clause that affirmatively asserts proof of absence."""
    hits: list[str] = []

    def scan(unit: str) -> None:
        if not _ABSENCE_LEMMA.search(unit):
            return
        for verb in _PROOF_LEMMA.finditer(unit):
            prefix = unit[max(0, verb.start() - _NEGATION_WINDOW) : verb.start()]
            if _GOVERNING_NEGATION.search(prefix):
                continue  # the proof verb is negated → an honest denial
            hits.append(unit.strip())
            break

    for clause in _CLAUSE_SPLIT.split(text):
        scan(clause)
    for sentence in _SENTENCE_SPLIT.split(text):
        comma_parts = sentence.split(",")
        for index in range(len(comma_parts) - 2):
            middle = comma_parts[index + 1]
            if 0 < len(middle.split()) <= 5:
                scan(f"{comma_parts[index]} {comma_parts[index + 2]}")
    return hits


# Documents that assert proof of absence in varied wordings. Every one must be
# rejected; each uses a distinct construction the fixed-phrase list would miss.
_PROVEN_ABSENCE_DOCUMENTS = (
    "The audit conclusively demonstrated the absence of any circuit-breaker halt.",
    "We have proven that no such interruption boundary exists.",
    "The nonexistence of a CME halt is hereby established.",
    "These records show the halt boundary to be absent.",
    "The investigation definitively confirms the boundary is nonexistent.",
    "It is proven that the interruption did not exist.",
    "Our sweep establishes the nonexistence of any resumption boundary.",
    "The boundary has been demonstrated to be absent from every source.",
    "Although we did not inspect the tapes, the analysis proves the absence of any halt.",
    "The search was exhaustive and therefore proves no such boundary exists.",
    "The records demonstrate, beyond any doubt, the absence of an interruption.",
    "The evidence conclusively establishes there is no interruption boundary.",
    "This proves none of the resumption boundaries exist.",
    "The review established zero interruptions existed.",
)
# Honest denials of proof-of-absence. Every one must pass; several negate the
# proof verb by subject ("No boundary was established") not by an adjacent word.
_HONEST_DENIAL_DOCUMENTS = (
    'The negative result is "not established", never "proven absent".',
    "Authoritative boundaries were not established; the result is not proven.",
    "The sweep did not demonstrate the absence of a halt.",
    "We cannot show that the boundary is absent.",
    "It remains unestablished whether any halt existed.",
    "The primary-source sweep terminated on resource limits, so nonexistence was not proven.",
    "No authoritative boundary could be established, and absence was never demonstrated.",
    "Absence of a boundary is not proven; the negative result is not established.",
)


def test_absence_of_evidence_is_never_stated_as_proof_of_absence():
    """Semantic, not syntactic. Matches proof-of-absence lemmas, not phrases."""
    text = CONTRACT.read_text(encoding="utf-8")
    # the honest denial must be present, and the document wraps, so match the
    # clause that does not span the wrap
    assert 'is "not established", never "proven absent"' in text
    # and the frozen contract itself must assert no proof of absence anywhere
    assert _proof_of_absence_clauses(text) == []


def test_detector_rejects_proof_of_absence_in_varied_wordings():
    """Negative control: every unlisted proven-absence wording is caught."""
    for document in _PROVEN_ABSENCE_DOCUMENTS:
        assert _proof_of_absence_clauses(document), document


def test_detector_accepts_honest_denials_of_proof_of_absence():
    """Guards against over-matching: honest 'not established' language passes."""
    for document in _HONEST_DENIAL_DOCUMENTS:
        assert _proof_of_absence_clauses(document) == [], document


def test_contract_marks_its_v2_counts_as_forecasts_not_attestations():
    """Fails if a forecast is ever restated as an observed result."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "FORECAST" in text
    assert "required preflight invariant" in text
    assert "Committed Phase 8 does NOT yet consume the fit predicate." in text
