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

# The approved negative-result text, pinned directly at a fixed structural
# boundary: the "Known limitations" heading through end of document. This is
# pinned as TEXT, so it does not depend on any pattern recognising the wording
# inside it.
LIMITATIONS_MARKER = "## 12. Known limitations"
LIMITATIONS_CHARS = 2_641
LIMITATIONS_SHA256 = "becedd703aaa75f26656f0cf2433759c23235e6e4c69d8ffa49e8264823f0e97"


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


# --- F-A: proof-of-absence guarding -----------------------------------------
#
# Three revisions of this guard have now overstated their own strength, so the
# claim is stated carefully here and the layers are kept separate.
#
# Revision 1 pinned one exact clause and five banned phrases. Revision 2 matched
# lemmas and called itself semantic; re-audit 1 produced bypasses. Revision 3
# added a "fail-closed exact allowlist" — but re-audit 2 showed the allowlist was
# only exact AFTER finite lemma patterns chose what entered it, so wording using
# no known lemma ("certified that every potential halt was impossible") produced
# no unapproved unit at all. An exact comparison over a set selected by an
# incomplete filter inherits that incompleteness.
#
# So the layers now are:
#
#   THE REAL GATE — _contract_gate_failures(). Pure text pinning, with no
#   pattern matching anywhere in it: the whole-file byte count and sha256, plus
#   the complete "Known limitations" section pinned directly at a fixed
#   structural boundary. ANY added, removed or reworded character fails it,
#   whatever vocabulary it uses. This is the only layer that protects against
#   arbitrary new wording, and it is what the negative controls exercise.
#
#   SUPPLEMENTARY — the unit allowlist and the heuristic below. Both rest on
#   finite lemma lists. Both are INCOMPLETE and neither is claimed otherwise;
#   test_supplementary_layers_are_lemma_limited_and_say_so pins a wording they
#   still miss. They exist to give a human reviewer a reason to look, not to
#   decide correctness.
#
# Approving new negative-result text therefore means updating the pinned hashes
# deliberately, which is a human review step by construction.

# Verbs and adverbs that assert epistemic certainty of a conclusion.
_PROOF_LEMMA = re.compile(
    r"\b(?:prov(?:e|es|en|ed|ing)|proof|"
    r"demonstrat(?:e|es|ed|ing|ion|ions)|"
    r"establish(?:es|ed|ing)|"
    r"shows?|shown|"
    r"confirm(?:s|ed|ing)?|"
    r"guarantee(?:s|d|ing)?|"
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
    r"there\s+(?:is|was|are|were)\s+no\b|"
    r"none\b[^.;:\n]{0,80}\bexists?|"
    r"zero\s+\w+\s+existed|"
    r"the\s+existence\s+of)",
    re.IGNORECASE,
)
# Idioms that assert absence WITH certainty on their own, needing no proof verb.
# "impossible" excludes "impossible to <verb>", which is an honest statement of
# what could not be determined, not a claim that something did not happen.
_ABSENCE_IDIOM = re.compile(
    r"\b(?:rul(?:e|es|ed|ing)\s+out|"
    r"exclud(?:e|es|ed|ing)\s+the\s+possibility|"
    r"eliminat(?:e|es|ed|ing)\s+the\s+possibility|"
    r"impossible\b(?!\s+to\s)|"
    r"(?:cannot|could\s+not|must\s+not)\s+have\s+(?:existed|occurred|happened))",
    re.IGNORECASE,
)
_GOVERNING_NEGATION = re.compile(
    r"\b(?:not|never|no|nor|cannot|neither|without|unable|fails?|failed)\b|n't",
    re.IGNORECASE,
)
# Units are SENTENCES, not comma-clauses. Splitting on commas is how revision 2
# lost "there is no halt, as proven" and the parenthetical construction.
_SENTENCE_SPLIT = re.compile(r"[.;:\n]")
# Only a negation close in front of the proof verb counts as governing it. An
# unbounded look-back let a far-away, unrelated "no" suppress a real assertion.
_NEGATION_WINDOW = 24


def _contract_gate_failures(payload: bytes) -> list[str]:
    """THE REAL GATE. Pure text pinning; contains no pattern matching at all.

    Returns the labels of every pin the payload violates. Because it compares
    bytes and hashes rather than searching for vocabulary, arbitrary new wording
    cannot slip past it — which is exactly what the lemma-driven layers cannot
    promise.
    """
    failures: list[str] = []
    if len(payload) != CONTRACT_BYTES:
        failures.append("byte-count")
    if hashlib.sha256(payload).hexdigest() != CONTRACT_SHA256:
        failures.append("sha256")
    if b"\r" in payload:
        failures.append("carriage-return")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        failures.append("not-utf8")
        return failures
    index = text.find(LIMITATIONS_MARKER)
    if index < 0:
        failures.append("limitations-section-missing")
    else:
        section = text[index:]
        if len(section) != LIMITATIONS_CHARS:
            failures.append("limitations-section")
        elif hashlib.sha256(section.encode("utf-8")).hexdigest() != LIMITATIONS_SHA256:
            failures.append("limitations-section")
    return failures


def _mask_absence(unit: str) -> str:
    """Blank absence spans so their own "no"/"not" cannot pose as a negation.

    Without this, "There is no halt, as proven by the sweep" reads its own
    absence marker as the negation of "proven" and escapes. The mask preserves
    offsets so the negation window still measures real distance.
    """
    chars = list(unit)
    for pattern in (_ABSENCE_LEMMA, _ABSENCE_IDIOM):
        for match in pattern.finditer(unit):
            for index in range(match.start(), match.end()):
                chars[index] = " "
    return "".join(chars)


def _negated(masked: str, start: int) -> bool:
    window = masked[max(0, start - _NEGATION_WINDOW) : start]
    return bool(_GOVERNING_NEGATION.search(window))


def _proof_of_absence_clauses(text: str) -> list[str]:
    """SUPPLEMENTARY heuristic. Incomplete by construction; see the header."""
    hits: list[str] = []
    for unit in _SENTENCE_SPLIT.split(text):
        masked = _mask_absence(unit)
        flagged = False
        for match in _ABSENCE_IDIOM.finditer(unit):
            if not _negated(masked, match.start()):
                flagged = True
                break
        if not flagged and _ABSENCE_LEMMA.search(unit):
            for match in _PROOF_LEMMA.finditer(unit):
                if not _negated(masked, match.start()):
                    flagged = True
                    break
        if flagged:
            hits.append(unit.strip())
    return hits


def _lemma_bearing_units(text: str) -> list[str]:
    """SUPPLEMENTARY. Only ever sees text the finite lemma lists recognise."""
    return [
        unit.strip()
        for unit in _SENTENCE_SPLIT.split(text)
        if _ABSENCE_LEMMA.search(unit)
        or _ABSENCE_IDIOM.search(unit)
        or _PROOF_LEMMA.search(unit)
    ]


# Supplementary reporting only. Each was read and approved individually: none
# asserts proof of absence, and the last is the contract's honest denial. This
# set is NOT the gate — see the header for why an exact comparison over a
# lemma-selected set is not a complete check.
APPROVED_NEGATIVE_RESULT_UNITS = frozenset({
    "in place because it never achieved a CLOSED audit, so there is no ratified",
    "**There is no calendar v2",
    "**There is no registered interruption input",
    "resumption boundaries were not established (D33)",
    "and no observed data of any kind, so inferring a close from absent data is not",
    "An absent or wrong-typed schedule raises",
    "bar is absent *because the session had already closed* therefore displays",
    "independently proves otherwise",
    "Reproduce S00 v1 exactly under its original definition first, confirming",
    "confirming the excluded sessions contribute nothing to the",
    'negative result is "not established", never "proven absent"',
})

# Documents asserting proof of absence. Every one must be flagged by the
# heuristic. The last two came from re-audit 2 and were missed by revision 3.
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
    "The sweep ruled out the existence of any CME halt.",
    "We excluded the possibility of an intraday interruption.",
    "The analysis eliminated the possibility of a resumption boundary.",
    "The halt cannot have existed, given the tape.",
    "Such a boundary could not have existed in this window.",
    "There is no halt, as proven by the rulebook sweep.",
    "The record, we now confirm, shows the absence of any boundary.",
    "No tape was recovered, and the sweep proves the absence of any halt.",
    # --- re-audit 2 escapes ---
    "The review certified that every potential halt was impossible.",
    "The evidence guarantees that interruptions were impossible.",
)
# Honest denials. Every one must stay clean, including the negated idiom forms
# and the "impossible to determine" construction.
_HONEST_DENIAL_DOCUMENTS = (
    'The negative result is "not established", never "proven absent".',
    "Authoritative boundaries were not established; the result is not proven.",
    "The sweep did not demonstrate the absence of a halt.",
    "We cannot show that the boundary is absent.",
    "It remains unestablished whether any halt existed.",
    "The primary-source sweep terminated on resource limits, so nonexistence was not proven.",
    "Absence of a boundary is not proven; the negative result is not established.",
    "We have not ruled out the existence of a halt.",
    "The sweep did not exclude the possibility of an interruption.",
    "It was impossible to establish the exact halt boundaries.",
    "We cannot guarantee the absence of a halt.",
)
# A wording the supplementary layers STILL miss, kept to prove the header's
# incompleteness statement is literal rather than modest. The real gate below
# rejects it regardless.
_LEMMA_BLIND_WORDING = "The record precludes any halt in this window."
# Characterization only: an honest denial the heuristic flags anyway, because the
# negation governs a distant subject rather than the verb. Recorded so the
# heuristic's imprecision is demonstrated. NOT evidence that it is correct.
_KNOWN_OVER_FLAGS = (
    "No authoritative boundary could be established, and absence was never demonstrated.",
)


def test_the_real_gate_passes_on_the_frozen_contract():
    """The whole-file and limitations-section pins hold on the current bytes."""
    assert _contract_gate_failures(CONTRACT.read_bytes()) == []


def test_the_real_gate_rejects_arbitrary_new_negative_result_wording():
    """Blocker 1 control: the gate is independent of lemma discovery.

    Every sentence here is appended to the real contract in memory only. Two are
    re-audit 2's escapes, which produced no unapproved unit and no heuristic hit;
    the third uses a verb no lemma list knows. All three must still fail the
    gate, because the gate compares text and never looks for vocabulary.
    """
    payload = CONTRACT.read_bytes()
    for sentence in (
        "The review certified that every potential halt was impossible.",
        "The evidence guarantees that interruptions were impossible.",
        _LEMMA_BLIND_WORDING,
    ):
        failures = _contract_gate_failures(payload + f"\n\n{sentence}\n".encode("utf-8"))
        assert "byte-count" in failures, sentence
        assert "sha256" in failures, sentence
        # the addition lands inside the pinned limitations section, which runs to
        # end of document, so that pin fires independently of the whole-file one
        assert "limitations-section" in failures, sentence


def test_the_limitations_heading_is_the_final_level_two_section():
    """Keeps the "heading through EOF" boundary meaning what it says.

    Appending a section 13 already fails the whole-file and section pins rather
    than passing silently, but this states the boundary assumption explicitly so
    a later editor cannot widen the pinned region by accident.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    assert text.count(LIMITATIONS_MARKER) == 1
    section = text[text.index(LIMITATIONS_MARKER) :]
    later_headings = [
        line
        for line in section.splitlines()[1:]
        if line.startswith("## ")
    ]
    assert later_headings == [], later_headings


def test_the_limitations_pin_is_independent_of_the_whole_file_pin():
    """Fails if the section pin silently degenerates into the file pin.

    Text inserted before the limitations heading must break the file pin while
    leaving the section pin intact — proving the two layers are distinct.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    edited = text.replace("# Session availability v2", "# Session availability v2 EDITED", 1)
    failures = _contract_gate_failures(edited.encode("utf-8"))
    assert "sha256" in failures
    assert "limitations-section" not in failures


def test_supplementary_layers_are_lemma_limited_and_say_so():
    """Pins the KNOWN incompleteness of the allowlist and the heuristic.

    Re-audit 2's finding, kept as a live witness: a wording outside the lemma
    lists produces no unapproved unit and no heuristic hit. If a future change
    makes this wording detected, that is fine — but the claim in the header must
    then be re-examined rather than quietly upgraded.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    revised = f"{text}\n\n{_LEMMA_BLIND_WORDING}\n"
    unapproved = [
        unit
        for unit in _lemma_bearing_units(revised)
        if unit not in APPROVED_NEGATIVE_RESULT_UNITS
    ]
    assert unapproved == [], "supplementary allowlist is not expected to catch this"
    assert _proof_of_absence_clauses(_LEMMA_BLIND_WORDING) == []
    # ...and the real gate catches it anyway
    assert _contract_gate_failures(revised.encode("utf-8")) != []


def test_supplementary_unit_allowlist_matches_the_contract():
    """Supplementary: lemma-bearing units still equal the approved set.

    Useful as a review aid and as a tripwire for lemma-visible edits. Not the
    gate: see test_supplementary_layers_are_lemma_limited_and_say_so.
    """
    units = _lemma_bearing_units(CONTRACT.read_text(encoding="utf-8"))
    unapproved = [unit for unit in units if unit not in APPROVED_NEGATIVE_RESULT_UNITS]
    assert unapproved == [], f"unapproved negative-result language: {unapproved}"
    assert set(units) == set(APPROVED_NEGATIVE_RESULT_UNITS)
    assert len(units) == 11


def test_absence_of_evidence_is_never_stated_as_proof_of_absence():
    """The contract states the honest denial and trips no heuristic flag."""
    text = CONTRACT.read_text(encoding="utf-8")
    # the document wraps, so match the clause that does not span the wrap
    assert 'is "not established", never "proven absent"' in text
    assert _proof_of_absence_clauses(text) == []


def test_heuristic_flags_proof_of_absence_including_every_audit_escape():
    """Negative control: each proven-absence wording, incl. audit escapes, flags."""
    for document in _PROVEN_ABSENCE_DOCUMENTS:
        assert _proof_of_absence_clauses(document), document


def test_heuristic_accepts_honest_denials_of_proof_of_absence():
    """Guards against the heuristic degenerating into flagging everything."""
    for document in _HONEST_DENIAL_DOCUMENTS:
        assert _proof_of_absence_clauses(document) == [], document


def test_characterization_known_heuristic_over_flag():
    """CHARACTERIZATION ONLY. Records current behaviour, proves nothing correct.

    The heuristic flags this honest denial. That is a false positive, pinned so
    it is visible. It is not evidence that the heuristic is semantically sound.
    """
    for document in _KNOWN_OVER_FLAGS:
        assert _proof_of_absence_clauses(document), document


def test_an_unrelated_earlier_negation_does_not_suppress_a_proof_assertion():
    """Re-audit 1 finding: a far-away 'no' must not neutralise a real claim.

    Pins the two mechanisms separately — bounded negation window, and masking an
    absence marker so it cannot pose as the negation of its own proof verb.
    """
    assert _proof_of_absence_clauses(
        "No tape was recovered, and the sweep proves the absence of any halt."
    )
    assert _proof_of_absence_clauses("There is no halt, as proven by the rulebook sweep.")
    # the mask preserves offsets, so a genuinely adjacent negation still governs
    assert _proof_of_absence_clauses("The sweep did not prove the absence of a halt.") == []


def test_contract_marks_its_v2_counts_as_forecasts_not_attestations():
    """Fails if a forecast is ever restated as an observed result."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert "FORECAST" in text
    assert "required preflight invariant" in text
    assert "Committed Phase 8 does NOT yet consume the fit predicate." in text
