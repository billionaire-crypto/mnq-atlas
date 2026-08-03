"""Independent structural inventory witnesses for Phase 8 step 4."""

from __future__ import annotations

import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import MigrationCell, MigrationSummary
from mnq_lab.phase8.contrasts import CellKey
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.inventory import (
    ALTERNATIVE_ARM_IDS,
    PATH_ESTIMANDS,
    PRIMARY_ARM_ID,
    SUPPORT_KINDS,
    assemble_status_rows,
    declared_result_rows,
)


def test_phase8_arm_inventory_is_literal_and_bound_to_phase7_order():
    assert PRIMARY_ARM_ID == "primary_ewma78_permissive_expanding"
    assert ALTERNATIVE_ARM_IDS == (
        "coverage_strict",
        "ewma39",
        "ewma156",
        "mad78",
        "threshold_rolling60",
        "threshold_shift_m05",
        "threshold_shift_m02",
        "threshold_shift_p02",
        "threshold_shift_p05",
    )
    assert (PRIMARY_ARM_ID, *ALTERNATIVE_ARM_IDS) == tuple(
        config.arm_id for config in ARM_CONFIGS
    )
    assert PATH_ESTIMANDS == (
        "fully_labeled_1m_grid",
        "observed_bar_path",
    )
    assert SUPPORT_KINDS == ("horizon_specific", "common_support")


def test_primary_arm_has_the_complete_hard_counted_inventory():
    rows = declared_result_rows()
    primary = tuple(row for row in rows if row.arm_id == PRIMARY_ARM_ID)

    # 2 outcomes x 2 path estimands x 2 support kinds x 3 horizons x
    # 3 statistics x 3 population estimands x 15 target cells x
    # (1 absolute weighting + 4 contrasts x 2 comparative weightings).
    assert len(primary) == 29_160
    assert {row.outcome_name for row in primary} == {
        "downward_excursion_ticks",
        "upward_excursion_ticks",
    }
    assert {row.path_estimand for row in primary} == set(PATH_ESTIMANDS)
    assert {row.support_kind for row in primary} == set(SUPPORT_KINDS)
    assert {row.horizon_minutes for row in primary} == {15, 30, 60}
    assert {row.statistic for row in primary} == {"q50", "q75", "q90"}
    assert {row.population_estimand for row in primary} == {
        "prospective_cell",
        "common_session_paired",
        "standardized_shared_population",
    }
    assert all(row.migration_diagnostic_arm_id is None for row in primary)


def test_absolute_and_comparative_weighting_rows_are_both_exact():
    rows = declared_result_rows()
    primary = tuple(row for row in rows if row.arm_id == PRIMARY_ARM_ID)
    absolute = tuple(
        row for row in primary if row.contrast_name == "absolute_distribution"
    )
    comparative = tuple(
        row for row in primary if row.contrast_name == "phase_effect_given_vol"
    )

    assert {row.contrast_weighting for row in absolute} == {"not_applicable"}
    assert {row.contrast_weighting for row in comparative} == {
        "equal_phase_contrast",
        "natural_prevalence_contrast",
    }
    assert len(comparative) == 2 * len(absolute)


def test_each_alternative_arm_is_only_the_one_declared_surface():
    rows = declared_result_rows()
    alternatives = tuple(row for row in rows if row.arm_id != PRIMARY_ARM_ID)

    assert len(alternatives) == 270  # 9 arms x 15 cells x 2 weightings
    for arm_id in ALTERNATIVE_ARM_IDS:
        arm_rows = tuple(row for row in alternatives if row.arm_id == arm_id)
        assert len(arm_rows) == 30
        assert {row.outcome_name for row in arm_rows} == {
            "downward_excursion_ticks"
        }
        assert {row.path_estimand for row in arm_rows} == {
            "fully_labeled_1m_grid"
        }
        assert {row.support_kind for row in arm_rows} == {"horizon_specific"}
        assert {row.horizon_minutes for row in arm_rows} == {30}
        assert {row.statistic for row in arm_rows} == {"q90"}
        assert {row.contrast_name for row in arm_rows} == {
            "vol_effect_given_phase"
        }
        assert {row.population_estimand for row in arm_rows} == {
            "prospective_cell"
        }
        assert {row.contrast_weighting for row in arm_rows} == {
            "equal_phase_contrast",
            "natural_prevalence_contrast",
        }
        assert {row.target_cell for row in arm_rows} == {
            CellKey(phase, state)
            for phase in ("open", "morning", "midday", "afternoon", "close")
            for state in ("low", "mid", "high")
        }
        assert {
            row.migration_diagnostic_arm_id for row in arm_rows
        } == {arm_id}


def test_inventory_order_starts_with_literal_axes_not_a_measured_sort():
    rows = declared_result_rows()
    first = rows[0]
    assert (
        first.arm_id,
        first.outcome_name,
        first.path_estimand,
        first.support_kind,
        first.horizon_minutes,
        first.statistic,
        first.contrast_name,
        first.population_estimand,
        first.contrast_weighting,
        first.target_cell,
    ) == (
        PRIMARY_ARM_ID,
        "downward_excursion_ticks",
        "fully_labeled_1m_grid",
        "horizon_specific",
        15,
        "q50",
        "absolute_distribution",
        "prospective_cell",
        "not_applicable",
        CellKey("open", "low"),
    )


def test_missing_declared_cell_halts_status_row_assembly():
    declared = declared_result_rows()[:2]
    ok = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    with pytest.raises(SpineError, match="missing declared result cell"):
        assemble_status_rows(declared, {declared[0]: ok})


def test_status_row_assembly_preserves_declaration_order_and_statuses_every_cell():
    declared = declared_result_rows()[:2]
    ok = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    assembled = assemble_status_rows(
        declared,
        {declared[1]: ok, declared[0]: ok},
    )
    assert tuple(row.spec for row in assembled) == declared
    assert all(row.status.status == "ok" for row in assembled)


def _migration_summary(arm_id):
    counts = {(0, 1): 1, (1, -1): 2, (-1, 2): 3}
    cells = tuple(
        MigrationCell(left, right, counts.get((left, right), 0))
        for left in (-1, 0, 1, 2)
        for right in (-1, 0, 1, 2)
    )
    return MigrationSummary(
        PRIMARY_ARM_ID,
        arm_id,
        cells,
        common_defined=1,
        changed_defined=1,
        changed_fraction=1.0,
        primary_defined_alternative_undefined=2,
        primary_undefined_alternative_defined=3,
    )


def test_alternative_status_row_requires_and_carries_its_phase7_migration_diagnostic():
    alternative = next(
        row for row in declared_result_rows() if row.arm_id == ALTERNATIVE_ARM_IDS[0]
    )
    ok = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    with pytest.raises(SpineError, match="missing Phase 7 migration diagnostic"):
        assemble_status_rows((alternative,), {alternative: ok})

    migration = _migration_summary(alternative.arm_id)
    assembled = assemble_status_rows(
        (alternative,),
        {alternative: ok},
        migration_by_arm={alternative.arm_id: migration},
    )
    assert assembled[0].migration_diagnostics is migration
