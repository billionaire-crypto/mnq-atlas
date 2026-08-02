"""Whole-tree artifact identity across legacy and compact dependency storage."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from mnq_lab.conditioners.artifacts import (
    build_phase7_artifact_bundle,
    write_phase7_artifacts,
)
from mnq_lab.conditioners.assignments import ThresholdTable
from mnq_lab.conditioners.pipeline import Phase7ConditionerPipeline
from mnq_lab.conditioners.seasonal import SeasonalProfileTable
from tests.phase7_pipeline_fixtures import synthetic_pipeline
from tests.test_phase7_artifacts import _anchor_columns, _environment, _files, _panel


def _legacy_clone(pipeline: Phase7ConditionerPipeline) -> Phase7ConditionerPipeline:
    seasonal = MappingProxyType(
        {
            arm_id: SeasonalProfileTable(
                arm_id,
                tuple(
                    replace(row, dependency_keys=row.dependency_keys)
                    for row in table.rows
                ),
            )
            for arm_id, table in pipeline.seasonal_profiles.items()
        }
    )
    thresholds = MappingProxyType(
        {
            arm_id: ThresholdTable(
                arm_id,
                tuple(
                    replace(row, dependency_keys=row.dependency_keys)
                    for row in table.rows
                ),
            )
            for arm_id, table in pipeline.threshold_tables.items()
        }
    )
    return Phase7ConditionerPipeline(
        seasonal,
        pipeline.vol_rel_tables,
        thresholds,
        pipeline.assignment_tables,
        pipeline.migration_summaries,
        pipeline.undefined_fractions,
    )


def _mutated_seasonal_pipeline(
    pipeline: Phase7ConditionerPipeline,
) -> Phase7ConditionerPipeline:
    tables = dict(pipeline.seasonal_profiles)
    arm_id = next(iter(tables))
    source = tables[arm_id]
    target = next(row for row in source.rows if row.seasonal_valid)
    mutated = replace(
        target,
        seasonal_profile=float(target.seasonal_profile + 1.0),
    )
    tables[arm_id] = SeasonalProfileTable(
        arm_id,
        tuple(mutated if row is target else row for row in source.rows),
    )
    return Phase7ConditionerPipeline(
        MappingProxyType(tables),
        pipeline.vol_rel_tables,
        pipeline.threshold_tables,
        pipeline.assignment_tables,
        pipeline.migration_summaries,
        pipeline.undefined_fractions,
    )


def test_complete_phase7_artifact_tree_is_byte_identical_and_can_fail(tmp_path):
    _, _, _, compact_pipeline = synthetic_pipeline(65)
    legacy_pipeline = _legacy_clone(compact_pipeline)
    compact_bundle = build_phase7_artifact_bundle(
        _anchor_columns(), compact_pipeline, _panel()
    )
    legacy_bundle = build_phase7_artifact_bundle(
        _anchor_columns(), legacy_pipeline, _panel()
    )
    compact_root = tmp_path / "compact"
    legacy_root = tmp_path / "legacy"
    environment = _environment()
    write_phase7_artifacts(
        compact_root,
        compact_bundle,
        source_build_id="dependency-identity-fixture",
        environment=environment,
    )
    write_phase7_artifacts(
        legacy_root,
        legacy_bundle,
        source_build_id="dependency-identity-fixture",
        environment=environment,
    )
    compact_files = _files(compact_root)
    legacy_files = _files(legacy_root)
    assert compact_files
    assert compact_files == legacy_files

    mutant_pipeline = _mutated_seasonal_pipeline(compact_pipeline)
    mutant_bundle = build_phase7_artifact_bundle(
        _anchor_columns(), mutant_pipeline, _panel()
    )
    mutant_root = tmp_path / "mutant"
    write_phase7_artifacts(
        mutant_root,
        mutant_bundle,
        source_build_id="dependency-identity-fixture",
        environment=environment,
    )
    mutant_files = _files(mutant_root)
    assert set(mutant_files) == set(compact_files)
    assert mutant_files != compact_files
    assert any(
        mutant_files[name] != compact_files[name]
        for name in compact_files
        if "seasonal_profiles" in name or name == "manifest.json"
    )
