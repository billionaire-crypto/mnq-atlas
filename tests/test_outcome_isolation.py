"""Non-vacuous conditioner/calendar and tier-isolation gates for Unit O."""

from __future__ import annotations

import ast
import inspect
import types

import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners import calendar as conditioner_calendar
from mnq_lab.conditioners import pipeline as conditioner_pipeline
from mnq_lab.outcomes import artifacts, excursions
from mnq_lab.spine.seal import LOCKED_STORE_DIRNAME
from tests.unit_o_fixtures import synthetic_outcome_columns, write_synthetic_store


class OutcomeIsolationSentinel(RuntimeError):
    pass


def _raise_sentinel(*args, **kwargs):
    raise OutcomeIsolationSentinel("forbidden conditioner/calendar loader reached")


def test_unit_o_public_api_has_no_conditioner_calendar_or_scale_arguments():
    signature = inspect.signature(excursions.build_outcome_table)
    assert list(signature.parameters) == ["store"]
    forbidden = {
        "conditioner",
        "assignment",
        "scale",
        "category",
        "threshold",
        "calendar",
    }
    assert forbidden.isdisjoint(signature.parameters)


def test_real_unit_o_modules_have_no_forbidden_import_or_path_literal():
    discovered = [excursions, artifacts]
    assert {module.__name__ for module in discovered} == {
        "mnq_lab.outcomes.excursions",
        "mnq_lab.outcomes.artifacts",
    }
    for module in discovered:
        tree = ast.parse(inspect.getsource(module), filename=inspect.getsourcefile(module))
        imports = []
        strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
        assert not any(name.startswith("mnq_lab.conditioners") for name in imports)
        assert not any("calendar_inputs" in value for value in strings)
        assert not any(LOCKED_STORE_DIRNAME in value for value in strings)


def test_every_public_unit_o_entrypoint_avoids_both_real_sentinels(
    tmp_path, monkeypatch
):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    monkeypatch.setattr(conditioner_pipeline, "build_conditioner_pipeline", _raise_sentinel)
    monkeypatch.setattr(conditioner_calendar, "load_accepted_calendar", _raise_sentinel)

    table = excursions.build_outcome_table(store)
    assert table.row_count > 0
    manifest = artifacts.write_outcome_artifact(
        tmp_path / "artifact",
        table,
        source_store=store,
        environment={
            "vcs": "git",
            "commit": "a" * 40,
            "branch": "synthetic",
            "dirty": False,
            "python": "test",
            "numpy": "test",
            "pandas": "test",
            "platform": "test",
            "machine": "test",
            "pipeline_version": "spine-1.0.0",
        },
    )
    assert manifest["row_count"] == table.row_count


def test_in_memory_mutant_of_real_excursion_module_reaches_sentinel(
    tmp_path, monkeypatch
):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    monkeypatch.setattr(conditioner_pipeline, "build_conditioner_pipeline", _raise_sentinel)
    mutant = types.ModuleType("_unit_o_conditioner_access_mutant")
    mutant.__dict__.update(excursions.__dict__)
    real_build = excursions.build_outcome_table

    def mutated_build(store):
        conditioner_pipeline.build_conditioner_pipeline(None, None, None)
        return real_build(store)

    mutant.build_outcome_table = mutated_build
    assert mutant.build_outcome_table is not real_build
    with pytest.raises(OutcomeIsolationSentinel):
        mutant.build_outcome_table(store)


def test_artifact_writer_refuses_locked_tier_names_even_in_metadata(
    tmp_path,
):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    table = excursions.build_outcome_table(store)
    with pytest.raises(SpineError, match="forbidden tier"):
        artifacts.write_outcome_artifact(
            tmp_path / "artifact",
            table,
            source_store=store,
            environment={"note": LOCKED_STORE_DIRNAME},
        )
