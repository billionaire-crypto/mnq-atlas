"""Independent synthetic witnesses for Phase 8 preregistration step 6."""

from __future__ import annotations

from dataclasses import fields
from itertools import combinations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import SESSION_PHASES, VOLATILITY_STATES, CellKey
from mnq_lab.phase8.interactions import (
    DESCRIPTIVE_ONLY_LABEL,
    INTERACTION_STATISTICS,
    INTERACTION_SUPPORT_KIND,
    MIN_CELL_ANCHORS,
    MIN_COMMON_SESSIONS,
    REFERENCE_CELL,
    REFERENCE_PHASE,
    REFERENCE_VOLATILITY_STATE,
    InteractionRowSpec,
    assemble_interaction_rows,
    build_four_cell_support,
    declared_interaction_rows,
    evaluate_interaction,
    interaction_bootstrap_inputs,
    interaction_cells,
)


def _four_cell_rows(
    *,
    sessions=range(20),
    anchors_per_cell_session=2,
    target=CellKey("open", "high"),
):
    cells = interaction_cells(target)
    session_ids = []
    phases = []
    states = []
    values = []
    literal_values = (10, 3, 5, 1)
    for session_id in sessions:
        for cell, tick in zip(cells, literal_values, strict=True):
            count = (
                anchors_per_cell_session(cell, session_id)
                if callable(anchors_per_cell_session)
                else anchors_per_cell_session
            )
            for _ in range(count):
                session_ids.append(session_id)
                phases.append(cell.phase)
                states.append(cell.volatility_state)
                values.append(tick)
    return (
        np.asarray(session_ids),
        np.asarray(phases),
        np.asarray(states),
        np.ones(len(session_ids), dtype=np.bool_),
        np.asarray(values, dtype=np.int32),
    )


def _completion(cells, value=True):
    return {cell: value for cell in cells}


def _complete_lattice_fixture():
    session_ids = []
    phases = []
    states = []
    values = []
    cell_ticks = {}
    tick = 1
    for phase in SESSION_PHASES:
        for state in VOLATILITY_STATES:
            cell_ticks[CellKey(phase, state)] = tick
            tick += 3
    for session_id in range(20):
        for phase in SESSION_PHASES:
            for state in VOLATILITY_STATES:
                cell = CellKey(phase, state)
                for _ in range(2):
                    session_ids.append(session_id)
                    phases.append(phase)
                    states.append(state)
                    values.append(cell_ticks[cell])
    return (
        np.asarray(session_ids),
        np.asarray(phases),
        np.asarray(states),
        np.ones(len(session_ids), dtype=np.bool_),
        np.asarray(values, dtype=np.int32),
    )


def test_interaction_literals_and_inventory_are_exact_with_seven_eight_split():
    assert REFERENCE_PHASE == "midday"
    assert REFERENCE_VOLATILITY_STATE == "mid"
    assert REFERENCE_CELL == CellKey("midday", "mid")
    assert INTERACTION_SUPPORT_KIND == "four_cell_common_sessions"
    assert INTERACTION_STATISTICS == ("q50", "q90")
    assert MIN_COMMON_SESSIONS == 20
    assert MIN_CELL_ANCHORS == 30
    assert DESCRIPTIVE_ONLY_LABEL == "DESCRIPTIVE ONLY - NO P-VALUE"

    declared = declared_interaction_rows()
    assert len(declared) == 2 * 2 * 2 * 3 * 1 * 2 * 15
    assert {spec.population_estimand for spec in declared} == {
        "common_session_paired"
    }
    fixed_slice = tuple(
        spec
        for spec in declared
        if spec.outcome_name == "downward_excursion_ticks"
        and spec.path_estimand == "fully_labeled_1m_grid"
        and spec.support_kind == "horizon_specific"
        and spec.horizon_minutes == 15
        and spec.population_estimand == "prospective_cell"
    )
    assert len(fixed_slice) == 30
    for statistic in INTERACTION_STATISTICS:
        statistic_rows = tuple(row for row in fixed_slice if row.statistic == statistic)
        degenerate = tuple(row for row in statistic_rows if row.structurally_degenerate)
        nonreference = tuple(
            row for row in statistic_rows if not row.structurally_degenerate
        )
        assert len(degenerate) == 7
        assert len(nonreference) == 8

    with pytest.raises(SpineError, match="q50 and q90"):
        InteractionRowSpec(
            "primary_ewma78_permissive_expanding",
            "downward_excursion_ticks",
            "fully_labeled_1m_grid",
            "horizon_specific",
            15,
            "prospective_cell",
            "q75",
            CellKey("open", "low"),
        )


def test_four_cell_algebraic_order_and_reference_degeneracy_are_literal():
    assert interaction_cells(CellKey("open", "high")) == (
        CellKey("open", "high"),
        CellKey("open", "mid"),
        CellKey("midday", "high"),
        CellKey("midday", "mid"),
    )
    assert interaction_cells(CellKey("midday", "high")) == (
        CellKey("midday", "high"),
        CellKey("midday", "mid"),
        CellKey("midday", "high"),
        CellKey("midday", "mid"),
    )
    assert interaction_cells(CellKey("open", "mid")) == (
        CellKey("open", "mid"),
        CellKey("open", "mid"),
        CellKey("midday", "mid"),
        CellKey("midday", "mid"),
    )

    session_ids, phases, states, eligible, _ = _four_cell_rows()
    with pytest.raises(SpineError, match="degenerate interaction"):
        build_four_cell_support(
            session_ids,
            phases,
            states,
            eligible,
            CellKey("midday", "high"),
        )


def test_pairwise_intersections_do_not_substitute_for_four_way_support():
    target = CellKey("open", "high")
    cells = interaction_cells(target)
    session_ids = []
    phases = []
    states = []
    for missing_index, session_id in enumerate((101, 102, 103, 104)):
        for cell_index, cell in enumerate(cells):
            if cell_index != missing_index:
                session_ids.append(session_id)
                phases.append(cell.phase)
                states.append(cell.volatility_state)

    independently_observed = {
        cell: {
            session_ids[index]
            for index, (phase, state) in enumerate(zip(phases, states, strict=True))
            if (phase, state) == (cell.phase, cell.volatility_state)
        }
        for cell in cells
    }
    assert all(
        independently_observed[left] & independently_observed[right]
        for left, right in combinations(cells, 2)
    )
    assert not set.intersection(*(independently_observed[cell] for cell in cells))

    support = build_four_cell_support(
        np.asarray(session_ids),
        np.asarray(phases),
        np.asarray(states),
        np.ones(len(session_ids), dtype=np.bool_),
        target,
    )
    assert support.retained_session_ids == ()
    assert support.n_common_sessions == 0
    assert all(term.n_anchors == 0 for term in support.terms)
    assert all(term.n_sessions == 0 for term in support.terms)
    assert all(term.weight_ess is None for term in support.terms)

    evaluation = evaluate_interaction(
        np.asarray([1] * len(session_ids), dtype=np.int32),
        support,
        _completion(cells),
        "q50",
    )
    assert evaluation.status == "insufficient_interaction_support"
    assert evaluation.interaction_ticks is None
    assert evaluation.interaction_valid is False


def test_common_support_uses_session_equal_mass_inside_every_cell():
    target = CellKey("open", "high")
    cells = interaction_cells(target)

    def unequal_anchors(cell, session_id):
        return 1 if session_id < 10 else 2

    session_ids, phases, states, eligible, values = _four_cell_rows(
        anchors_per_cell_session=unequal_anchors
    )
    support = build_four_cell_support(
        session_ids, phases, states, eligible, target
    )
    assert support.retained_session_ids == tuple(range(20))
    assert support.n_common_sessions == 20
    for term in support.terms:
        assert term.n_anchors == 30
        assert term.n_sessions == 20
        assert term.weight_ess == pytest.approx(80 / 3)
        for session_id in range(20):
            session_mass = float(np.sum(term.weights[session_ids == session_id]))
            assert session_mass == pytest.approx(0.05)

    evaluation = evaluate_interaction(
        values, support, _completion(cells), "q90"
    )
    assert evaluation.status == "ok"
    assert evaluation.term_quantiles_ticks == (10, 3, 5, 1)
    assert evaluation.interaction_ticks == 3
    assert evaluation.interaction_valid is True


@pytest.mark.parametrize(
    ("sessions", "anchors_per_cell_session", "failed_completion_cell", "reason"),
    (
        (range(19), 2, None, "nineteen common sessions"),
        (
            range(20),
            lambda cell, session_id: (
                1
                if cell == CellKey("open", "high") and session_id < 11
                else 2
            ),
            None,
            "twenty-nine target anchors",
        ),
        (range(20), 2, CellKey("midday", "high"), "failed cell completion"),
    ),
)
def test_each_interaction_adequacy_requirement_has_a_named_failing_input(
    sessions, anchors_per_cell_session, failed_completion_cell, reason
):
    target = CellKey("open", "high")
    session_ids, phases, states, eligible, values = _four_cell_rows(
        sessions=sessions,
        anchors_per_cell_session=anchors_per_cell_session,
        target=target,
    )
    support = build_four_cell_support(
        session_ids, phases, states, eligible, target
    )
    completion = _completion(interaction_cells(target))
    if failed_completion_cell is not None:
        completion[failed_completion_cell] = False
    evaluation = evaluate_interaction(values, support, completion, "q50")
    assert reason
    assert evaluation.status == "insufficient_interaction_support"
    assert evaluation.status_flags == ("insufficient_interaction_support",)
    assert evaluation.interaction_ticks is None
    assert evaluation.interaction_valid is False


def test_lattice_assembly_emits_every_row_and_rejects_one_missing_cell():
    session_ids, phases, states, eligible, values = _complete_lattice_fixture()
    declared = tuple(
        spec
        for spec in declared_interaction_rows()
        if spec.outcome_name == "downward_excursion_ticks"
        and spec.path_estimand == "fully_labeled_1m_grid"
        and spec.support_kind == "horizon_specific"
        and spec.horizon_minutes == 15
        and spec.population_estimand == "prospective_cell"
    )
    support_by_target = {}
    evaluations = {}
    for spec in declared:
        if spec.structurally_degenerate:
            continue
        support = support_by_target.setdefault(
            spec.target_cell,
            build_four_cell_support(
                session_ids, phases, states, eligible, spec.target_cell
            ),
        )
        evaluations[spec] = evaluate_interaction(
            values,
            support,
            _completion(interaction_cells(spec.target_cell)),
            spec.statistic,
        )

    rows = assemble_interaction_rows(declared, evaluations)
    assert len(rows) == 30
    assert tuple(row.spec for row in rows) == declared
    for statistic in INTERACTION_STATISTICS:
        statistic_rows = tuple(row for row in rows if row.spec.statistic == statistic)
        assert sum(row.status == "degenerate_baseline" for row in statistic_rows) == 7
        assert sum(row.status == "ok" for row in statistic_rows) == 8
    for row in rows:
        assert row.panel_label == DESCRIPTIVE_ONLY_LABEL
        assert "p_value" not in {field.name for field in fields(row)}
        if row.status == "ok":
            assert row.common_n_sessions == 20
            assert len(row.cell_anchor_counts) == 4
            assert len(row.cell_session_counts) == 4
            assert len(row.cell_weight_ess) == 4
            assert all(count == 40 for _, count in row.cell_anchor_counts)
            assert all(count == 20 for _, count in row.cell_session_counts)
            assert all(ess == pytest.approx(40.0) for _, ess in row.cell_weight_ess)

    missing = dict(evaluations)
    missing.pop(next(iter(missing)))
    with pytest.raises(SpineError, match="missing declared interaction cell"):
        assemble_interaction_rows(declared, missing)


def test_q75_and_misordered_completion_cells_fail_closed():
    target = CellKey("open", "high")
    session_ids, phases, states, eligible, values = _four_cell_rows()
    support = build_four_cell_support(
        session_ids, phases, states, eligible, target
    )
    cells = interaction_cells(target)
    reversed_completion = {cell: True for cell in reversed(cells)}
    with pytest.raises(SpineError, match="structural cell order"):
        evaluate_interaction(values, support, reversed_completion, "q50")
    with pytest.raises(SpineError, match="q50 and q90"):
        evaluate_interaction(values, support, _completion(cells), "q75")


def test_ok_evaluation_translates_exactly_to_joint_bootstrap_terms_and_request():
    target = CellKey("open", "high")
    session_ids, phases, states, eligible, values = _four_cell_rows()
    support = build_four_cell_support(
        session_ids, phases, states, eligible, target
    )
    evaluation = evaluate_interaction(
        values, support, _completion(interaction_cells(target)), "q50"
    )
    terms, request = interaction_bootstrap_inputs(
        "open_high_q50", values, evaluation
    )

    assert len(terms) == 4
    assert request.request_id == "open_high_q50"
    assert request.term_ids == tuple(term.term_id for term in terms)
    assert request.status == "ok"
    for term, expected in zip(terms, support.terms, strict=True):
        assert term.statistic == "q50"
        assert np.array_equal(term.values, values)
        assert np.array_equal(term.eligibility_mask, expected.eligibility_mask)
        assert np.array_equal(term.weights, expected.weights)

    thin_ids, thin_phases, thin_states, thin_eligible, thin_values = (
        _four_cell_rows(sessions=range(19))
    )
    thin_support = build_four_cell_support(
        thin_ids, thin_phases, thin_states, thin_eligible, target
    )
    thin = evaluate_interaction(
        thin_values,
        thin_support,
        _completion(interaction_cells(target)),
        "q50",
    )
    with pytest.raises(SpineError, match="only ok interaction evaluations"):
        interaction_bootstrap_inputs("thin_mutant", thin_values, thin)
