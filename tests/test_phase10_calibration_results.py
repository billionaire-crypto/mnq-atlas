"""Synthetic-only Slice 3 witnesses; no corpus or calibration is executed."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import inspect
import json

import numpy as np
import pytest

from mnq_lab import SpineError
import mnq_lab.phase10.calibration_results as results_module
from mnq_lab.phase10.calibration import NOMINAL_ALPHA, NULL_REPLICATIONS
from mnq_lab.phase10.calibration_controls import PLANTED_EFFECT_LADDER
from mnq_lab.phase10.calibration_entropy import (
    CALIBRATION_ROOT_LABEL,
    CALIBRATION_ROOT_SHA256,
)
from mnq_lab.phase10.calibration_results import (
    CalibrationReplicationResult,
    LocalizationResult,
    OperationalTelemetry,
    QuartetMemberResult,
    REJECTION_RULE_IDENTITY,
    ReplicationScientificPayload,
    canonical_scientific_payload_bytes,
    exact_co_maximal_regions,
    localization_overlap,
    mean_localization_overlap,
    planted_target_cells,
    rejection_event,
    scientific_payload_hash,
    seal_scientific_payload,
    validate_scientific_payload,
)
from mnq_lab.phase10.contract import PERMUTATION_POPULATION, load_phase10_contract
from mnq_lab.phase10.pvalue import permutation_pvalue
from mnq_lab.phase10.surface import SurfaceRegion, SurfaceStatistic, coherence_statistic


def _region(
    plane: int,
    sign: str,
    cells: tuple[tuple[int, int], ...],
    statistic: float,
) -> SurfaceRegion:
    return SurfaceRegion(
        plane_index=plane,
        sign=sign,
        cells=cells,
        mean_z=2.0 if sign == "positive" else -2.0,
        stability=1.0,
        statistic=statistic,
    )


def _binding_surface() -> SurfaceStatistic:
    return SurfaceStatistic(
        4.0,
        (
            _region(0, "positive", ((1, 2), (2, 2), (3, 2)), 4.0),
            _region(1, "positive", ((1, 2), (2, 2), (2, 1)), 4.0),
            _region(1, "negative", ((0, 0),), 4.0),
            _region(0, "positive", ((4, 0),), 3.999999999999),
        ),
    )


def _assert_rejection_contract(predicate, alpha):
    assert predicate(alpha)
    assert not predicate(float(np.nextafter(alpha, 1.0)))


def test_rejection_predicate_uses_imported_alpha_inclusively():
    _assert_rejection_contract(rejection_event, NOMINAL_ALPHA)


def test_strict_rejection_mutant_fails_the_positive_helper():
    with pytest.raises(AssertionError):
        _assert_rejection_contract(lambda value: value < NOMINAL_ALPHA, NOMINAL_ALPHA)


def test_fresh_alpha_literal_mutant_fails_the_positive_helper(monkeypatch):
    monkeypatch.setattr(results_module, "NOMINAL_ALPHA", 0.10)
    _assert_rejection_contract(results_module.rejection_event, 0.10)
    with pytest.raises(AssertionError):
        _assert_rejection_contract(lambda value: value <= 0.05, 0.10)


def _assert_rank_boundary(predicate, pvalue_function):
    observed = 1.0
    rejects = np.concatenate((np.ones(249), np.zeros(4999 - 249)))
    does_not_reject = np.concatenate((np.ones(250), np.zeros(4999 - 250)))
    left = pvalue_function(observed, rejects)
    right = pvalue_function(observed, does_not_reject)
    assert left == 250.0 / 5000.0
    assert right == 251.0 / 5000.0
    assert predicate(left)
    assert not predicate(right)


def test_frozen_4999_rank_arithmetic_covers_exactly_250_positions():
    _assert_rank_boundary(rejection_event, permutation_pvalue)


def test_rank_boundary_strict_mutant_fails_the_positive_helper():
    with pytest.raises(AssertionError):
        _assert_rank_boundary(lambda value: value < NOMINAL_ALPHA, permutation_pvalue)


def _assert_target_derivation(function):
    expected = frozenset(
        (results_module.SESSION_PHASES.index(phase), results_module.VOLATILITY_STATES.index("high"))
        for phase in results_module.PLANTED_EFFECT_PHASES
    )
    assert function() == expected


def test_planted_target_is_derived_from_imported_axes():
    _assert_target_derivation(planted_target_cells)


def test_hardcoded_target_mutant_fails_the_positive_helper(monkeypatch):
    monkeypatch.setattr(
        results_module,
        "SESSION_PHASES",
        ("morning", "open", "midday", "afternoon", "close"),
    )
    _assert_target_derivation(results_module.planted_target_cells)
    with pytest.raises(AssertionError):
        _assert_target_derivation(lambda: frozenset(((1, 2), (2, 2), (3, 2))))


def test_literal_high_column_mutant_fails_the_positive_helper(monkeypatch):
    monkeypatch.setattr(
        results_module,
        "VOLATILITY_STATES",
        ("high", "low", "mid"),
    )
    _assert_target_derivation(results_module.planted_target_cells)
    with pytest.raises(AssertionError):
        _assert_target_derivation(
            lambda: frozenset(
                (results_module.SESSION_PHASES.index(phase), 2)
                for phase in results_module.PLANTED_EFFECT_PHASES
            )
        )


def _assert_binding_localization(function):
    surface = _binding_surface()
    result = function(surface, True)
    assert isinstance(result, LocalizationResult)
    assert result.co_maximal_regions == surface.regions[:3]
    assert result.overlap == 0.5
    assert result.overlap != 1.0
    assert result.overlap != 0.75
    assert function(surface, False) == LocalizationResult(0.0, ())
    assert function(SurfaceStatistic(0.0, ()), True) == LocalizationResult(0.0, ())
    try:
        function(SurfaceStatistic(4.0, surface.regions[3:]), True)
    except SpineError as exc:
        assert "no exact co-maximal" in str(exc)
    else:
        raise AssertionError("positive surface without an exact co-maximum did not halt")


def test_localization_mean_wrong_sign_exact_tie_and_zero_rules_bind():
    _assert_binding_localization(localization_overlap)


def _tolerance_mutant(surface, rejected):
    if not rejected:
        return LocalizationResult(0.0, ())
    regions = tuple(
        region for region in surface.regions if np.isclose(region.statistic, surface.value)
    )
    if surface.value > 0.0 and not regions:
        raise SpineError("positive surface statistic has no exact co-maximal region")
    if not regions:
        return LocalizationResult(0.0, ())
    target = planted_target_cells()
    values = [
        0.0
        if region.sign == "negative"
        else len(set(region.cells) & target) / len(set(region.cells) | target)
        for region in regions
    ]
    return LocalizationResult(sum(values) / len(values), regions)


def _maximum_mutant(surface, rejected):
    result = localization_overlap(surface, rejected)
    if not rejected:
        return result
    target = planted_target_cells()
    values = [
        0.0
        if region.sign == "negative"
        else len(set(region.cells) & target) / len(set(region.cells) | target)
        for region in result.co_maximal_regions
    ]
    return LocalizationResult(sorted(values)[-1], result.co_maximal_regions)


def _filter_negative_mutant(surface, rejected):
    if not rejected:
        return LocalizationResult(0.0, ())
    regions = tuple(
        region
        for region in exact_co_maximal_regions(surface)
        if region.sign == "positive"
    )
    target = planted_target_cells()
    values = [len(set(region.cells) & target) / len(set(region.cells) | target) for region in regions]
    return LocalizationResult(sum(values) / len(values), regions)


def _drop_negative_denominator_mutant(surface, rejected):
    if not rejected:
        return LocalizationResult(0.0, ())
    regions = exact_co_maximal_regions(surface)
    target = planted_target_cells()
    values = [
        len(set(region.cells) & target) / len(set(region.cells) | target)
        for region in regions
        if region.sign == "positive"
    ]
    return LocalizationResult(sum(values) / len(values), regions)


def _plane_matching_mutant(surface, rejected):
    result = localization_overlap(surface, rejected)
    if not rejected:
        return result
    target = planted_target_cells()
    values = [
        0.0
        if region.sign == "negative" or region.plane_index != 0
        else len(set(region.cells) & target) / len(set(region.cells) | target)
        for region in result.co_maximal_regions
    ]
    return LocalizationResult(sum(values) / len(values), result.co_maximal_regions)


def _wrong_denominator_mutant(surface, rejected, denominator):
    if not rejected:
        return LocalizationResult(0.0, ())
    regions = exact_co_maximal_regions(surface)
    target = planted_target_cells()
    values = []
    for region in regions:
        if region.sign == "negative":
            values.append(0.0)
        else:
            cells = set(region.cells)
            divisor = len(target) if denominator == "target" else len(cells)
            values.append(len(cells & target) / divisor)
    return LocalizationResult(sum(values) / len(values), regions)


@pytest.mark.parametrize(
    "mutant",
    (
        _tolerance_mutant,
        _maximum_mutant,
        _filter_negative_mutant,
        _drop_negative_denominator_mutant,
        _plane_matching_mutant,
        lambda surface, rejected: localization_overlap(surface, rejected).overlap,
        lambda surface, rejected: LocalizationResult(0.25, ()) if not rejected else localization_overlap(surface, True),
        lambda surface, rejected: LocalizationResult(0.25, ()) if surface.value == 0.0 else localization_overlap(surface, rejected),
        lambda surface, rejected: LocalizationResult(0.0, ()) if surface.value > 0.0 and surface.regions == _binding_surface().regions[3:] else localization_overlap(surface, rejected),
        lambda surface, rejected: (_ for _ in ()).throw(SpineError("zero halt")) if surface.value == 0.0 else localization_overlap(surface, rejected),
        lambda surface, rejected: _wrong_denominator_mutant(surface, rejected, "target"),
        lambda surface, rejected: _wrong_denominator_mutant(surface, rejected, "region"),
    ),
)
def test_localization_mutants_fail_the_same_binding_helper(mutant):
    with pytest.raises((AssertionError, SpineError)):
        _assert_binding_localization(mutant)


def _assert_plane_independence(function):
    target = tuple(sorted(planted_target_cells()))
    left = SurfaceStatistic(2.0, (_region(0, "positive", target, 2.0),))
    right = SurfaceStatistic(2.0, (_region(1, "positive", target, 2.0),))
    assert function(left, True).overlap == 1.0
    assert function(right, True).overlap == 1.0


def test_plane_identity_is_ignored_for_overlap():
    _assert_plane_independence(localization_overlap)


def test_plane_matching_mutant_fails_a_binding_cross_plane_assertion():
    with pytest.raises(AssertionError):
        _assert_plane_independence(_plane_matching_mutant)


def _assert_realistic_synthetic_surface(statistic_function, localizer):
    z = np.zeros((2, 5, 3), dtype=np.float64)
    valid = np.ones(z.shape, dtype=np.bool_)
    z[0, 1:4, 2] = 2.0
    years = np.repeat(z[np.newaxis], 3, axis=0)
    year_valid = np.ones(years.shape, dtype=np.bool_)
    surface = statistic_function(z, valid, years, year_valid)
    result = localizer(surface, True)
    assert result.overlap == 1.0
    assert result.co_maximal_regions
    assert all(region.statistic == surface.value for region in result.co_maximal_regions)


def test_real_coherence_statistic_supplies_an_exact_positive_maximizer():
    _assert_realistic_synthetic_surface(coherence_statistic, localization_overlap)


def test_realistic_surface_wrong_overlap_mutant_fails_the_positive_helper():
    def wrong_overlap(surface, rejected):
        result = localization_overlap(surface, rejected)
        return LocalizationResult(0.0, result.co_maximal_regions)

    with pytest.raises(AssertionError):
        _assert_realistic_synthetic_surface(coherence_statistic, wrong_overlap)


def _assert_aggregation_contract(function):
    values = (0.0,) * (NULL_REPLICATIONS - 1) + (1.0,)
    assert function(values) == 1.0 / NULL_REPLICATIONS


def test_localization_aggregation_includes_all_300_values_and_zeros():
    _assert_aggregation_contract(mean_localization_overlap)


def test_rejected_only_aggregation_mutant_fails_the_positive_helper():
    def rejected_only(values):
        retained = tuple(value for value in values if value != 0.0)
        return sum(retained) / len(retained)

    with pytest.raises(AssertionError):
        _assert_aggregation_contract(rejected_only)


def _assert_aggregation_guards(function):
    try:
        function((0.0,) * 299)
    except SpineError as exc:
        assert "declared 300" in str(exc)
    else:
        raise AssertionError("short localization sequence was accepted")
    for bad in (True, -0.1, 1.1, np.nan):
        values = (0.0,) * 299 + (bad,)
        try:
            function(values)
        except SpineError as exc:
            assert "inside [0,1]" in str(exc)
        else:
            raise AssertionError("invalid localization value was accepted")


def test_aggregation_rejects_short_invalid_and_nonfinite_sequences():
    _assert_aggregation_guards(mean_localization_overlap)


def test_aggregation_guard_mutants_fail_the_positive_helper():
    def accepts_short(values):
        supplied = tuple(values)
        if len(supplied) == 299:
            raise SpineError("localization value must be one finite real inside [0,1]")
        return mean_localization_overlap(supplied)

    def accepts_invalid(values):
        supplied = tuple(values)
        if len(supplied) == 300 and supplied[-1] in (True, -0.1, 1.1):
            raise SpineError("localization values must match the declared 300 replications")
        if len(supplied) == 300 and np.isnan(supplied[-1]):
            raise SpineError("localization values must match the declared 300 replications")
        return mean_localization_overlap(supplied)

    for mutant in (accepts_short, accepts_invalid):
        with pytest.raises(AssertionError):
            _assert_aggregation_guards(mutant)


def _member(name, magnitude, p_value, rejected, overlap):
    surface = _binding_surface()
    co_maximal = exact_co_maximal_regions(surface)
    return QuartetMemberResult(
        member=name,
        effect_magnitude_ticks=magnitude,
        p_value=p_value,
        rejected=rejected,
        observed_statistic=surface.value,
        retained_regions=surface.regions,
        co_maximal_regions=co_maximal,
        localization_overlap=overlap,
        structural_statuses=("ok",),
        classified_failures=(),
    )


def _payload() -> ReplicationScientificPayload:
    contract = load_phase10_contract()
    return ReplicationScientificPayload(
        replication_index=7,
        calibration_root_label=CALIBRATION_ROOT_LABEL,
        calibration_root_digest=CALIBRATION_ROOT_SHA256,
        control_spawn_key=(7, 0),
        ensemble_spawn_key=(7, 1),
        completion_state="complete",
        attempt_lineage=("attempt-1",),
        permutations=contract.permutations_final,
        rejection_rule_identity=REJECTION_RULE_IDENTITY,
        formal_population_identity=PERMUTATION_POPULATION,
        weighting_planes=contract.weighting_planes,
        quartet_members=(
            _member("null", 0, 0.10, False, None),
            _member("weak", PLANTED_EFFECT_LADDER[0], 0.05, True, 0.5),
            _member("medium", PLANTED_EFFECT_LADDER[1], 0.04, True, 0.5),
            _member("strong", PLANTED_EFFECT_LADDER[2], 0.03, True, 0.5),
        ),
        structural_statuses=("complete",),
        classified_failures=(),
        code_identity="code-sha256",
        package_identity="package-lock-sha256",
        corpus_identity="corpus-manifest-sha256",
        environment_identity="environment-sha256",
        worker_configuration_identity="worker-config-sha256",
    )


PAYLOAD_FIELD_NAMES = (
    "replication_index",
    "calibration_root_label",
    "calibration_root_digest",
    "control_spawn_key",
    "ensemble_spawn_key",
    "completion_state",
    "attempt_lineage",
    "permutations",
    "rejection_rule_identity",
    "formal_population_identity",
    "weighting_planes",
    "quartet_members",
    "structural_statuses",
    "classified_failures",
    "code_identity",
    "package_identity",
    "corpus_identity",
    "environment_identity",
    "worker_configuration_identity",
)


def _assert_schema_shape(payload_type, telemetry_type, hash_function):
    assert tuple(field.name for field in fields(payload_type)) == PAYLOAD_FIELD_NAMES
    assert tuple(field.name for field in fields(telemetry_type)) == (
        "elapsed_seconds",
        "cpu_seconds",
        "peak_memory_bytes",
        "host_telemetry",
    )
    assert not set(PAYLOAD_FIELD_NAMES) & {
        "elapsed_seconds",
        "cpu_seconds",
        "peak_memory_bytes",
        "host_telemetry",
    }
    assert tuple(inspect.signature(hash_function).parameters) == ("payload",)


def test_operational_telemetry_is_structurally_outside_scientific_payload():
    _assert_schema_shape(
        ReplicationScientificPayload,
        OperationalTelemetry,
        scientific_payload_hash,
    )


def test_telemetry_inside_payload_mutant_fails_the_positive_schema_helper():
    class MutantPayload:
        pass

    MutantPayload.__dataclass_fields__ = {
        **ReplicationScientificPayload.__dataclass_fields__,
        "elapsed_seconds": OperationalTelemetry.__dataclass_fields__["elapsed_seconds"],
    }
    with pytest.raises(AssertionError):
        _assert_schema_shape(MutantPayload, OperationalTelemetry, scientific_payload_hash)


def test_hash_function_with_telemetry_parameter_fails_the_schema_helper():
    def mutant_hash(payload, telemetry):
        return scientific_payload_hash(payload), telemetry

    with pytest.raises(AssertionError):
        _assert_schema_shape(
            ReplicationScientificPayload,
            OperationalTelemetry,
            mutant_hash,
        )


def _assert_payload_valid(validator, payload):
    assert validator(payload) is payload


def test_complete_scientific_schema_validates_all_quartet_members():
    payload = _payload()
    _assert_payload_valid(validate_scientific_payload, payload)


@pytest.mark.parametrize(
    "mutator,message",
    (
        (lambda p: replace(p, replication_index=300), "replication index"),
        (lambda p: replace(p, calibration_root_label="wrong"), "root label"),
        (lambda p: replace(p, calibration_root_digest="wrong"), "root digest"),
        (lambda p: replace(p, control_spawn_key=(7, 1)), "control spawn"),
        (lambda p: replace(p, ensemble_spawn_key=(7, 0)), "ensemble spawn"),
        (lambda p: replace(p, completion_state="unknown"), "completion state"),
        (lambda p: replace(p, attempt_lineage=()), "attempt lineage"),
        (lambda p: replace(p, permutations=2), "permutation count"),
        (lambda p: replace(p, rejection_rule_identity="wrong"), "rejection rule"),
        (lambda p: replace(p, formal_population_identity="wrong"), "formal population"),
        (lambda p: replace(p, weighting_planes=tuple(reversed(p.weighting_planes))), "weighting-plane"),
        (lambda p: replace(p, quartet_members=p.quartet_members[:-1]), "complete quartet"),
        (lambda p: replace(p, code_identity=""), "code_identity"),
    ),
)
def test_payload_field_mutants_fail_the_same_validation_helper(mutator, message):
    with pytest.raises(SpineError, match=message):
        _assert_payload_valid(validate_scientific_payload, mutator(_payload()))


def test_member_pvalue_region_inventory_and_overlap_mutants_fail_closed():
    payload = _payload()
    weak = payload.quartet_members[1]
    mutants = (
        (replace(weak, member="medium"), "identity or effect"),
        (replace(weak, effect_magnitude_ticks=11), "identity or effect"),
        (replace(weak, rejected=False), "p-value and rejection"),
        (replace(weak, co_maximal_regions=weak.co_maximal_regions[:-1]), "co-maximal regions differ"),
        (replace(weak, retained_regions=weak.retained_regions[1:]), "co-maximal regions differ"),
        (replace(weak, localization_overlap=1.0), "localization overlap differs"),
    )
    for mutant, message in mutants:
        members = list(payload.quartet_members)
        members[1] = mutant
        changed = replace(payload, quartet_members=tuple(members))
        with pytest.raises(SpineError, match=message):
            _assert_payload_valid(validate_scientific_payload, changed)


def _assert_canonical_contract(serializer, hasher):
    payload = _payload()
    left = serializer(payload)
    right = serializer(replace(payload))
    assert left == right
    assert left == json.dumps(
        json.loads(left),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    assert b'"p_value_hex":"0x1.999999999999ap-4"' in left
    assert b'"retained_regions"' in left
    assert b'"co_maximal_regions"' in left
    assert b'"elapsed_seconds"' not in left
    assert b'"host_telemetry"' not in left
    assert b'"minimum_p_value"' not in left
    assert hasher(payload) == hashlib.sha256(left).hexdigest()
    changed = replace(payload, code_identity="different-code")
    assert hasher(changed) != hasher(payload)


def _assert_mapping_completeness(
    payload_mapper,
    member_mapper=results_module._member_mapping,
    region_mapper=results_module._region_mapping,
):
    payload = _payload()
    mapped_payload = payload_mapper(payload)
    for field in fields(ReplicationScientificPayload):
        candidates = (field.name, f"{field.name}_hex")
        assert sum(candidate in mapped_payload for candidate in candidates) == 1

    member = payload.quartet_members[1]
    mapped_member = member_mapper(member)
    for field in fields(QuartetMemberResult):
        candidates = (field.name, f"{field.name}_hex")
        assert sum(candidate in mapped_member for candidate in candidates) == 1

    region = member.retained_regions[0]
    mapped_region = region_mapper(region)
    for field in fields(SurfaceRegion):
        candidates = (field.name, f"{field.name}_hex")
        assert sum(candidate in mapped_region for candidate in candidates) == 1

    payload_free_form = {
        field.name: field
        for field in fields(ReplicationScientificPayload)
        if field.name in {
            "attempt_lineage",
            "structural_statuses",
            "classified_failures",
            "code_identity",
            "package_identity",
            "corpus_identity",
            "environment_identity",
            "worker_configuration_identity",
        }
    }
    for name in payload_free_form:
        original = getattr(payload, name)
        changed_value = (
            (*original, "hash-witness")
            if isinstance(original, tuple)
            else f"{original}-hash-witness"
        )
        assert scientific_payload_hash(replace(payload, **{name: changed_value})) != scientific_payload_hash(payload)

    for field in fields(QuartetMemberResult):
        if field.name not in {"structural_statuses", "classified_failures"}:
            continue
        original = getattr(member, field.name)
        changed_member = replace(member, **{field.name: (*original, "hash-witness")})
        quartet = list(payload.quartet_members)
        quartet[1] = changed_member
        assert scientific_payload_hash(replace(payload, quartet_members=tuple(quartet))) != scientific_payload_hash(payload)


def test_canonical_mapping_completeness_is_derived_from_dataclass_fields():
    _assert_mapping_completeness(results_module._scientific_mapping)


def test_mapping_with_one_field_removed_fails_the_same_completeness_witness():
    def missing_worker_configuration(payload):
        mapped = results_module._scientific_mapping(payload)
        mapped.pop("worker_configuration_identity")
        return mapped

    with pytest.raises(AssertionError):
        _assert_mapping_completeness(missing_worker_configuration)


def test_canonical_serialization_is_exact_deterministic_and_complete():
    _assert_canonical_contract(canonical_scientific_payload_bytes, scientific_payload_hash)


def _assert_sorted_serialization_call(source_provider):
    source = source_provider()
    assert "sort_keys=True" in source


def test_canonical_serializer_explicitly_sorts_keys():
    _assert_sorted_serialization_call(
        lambda: inspect.getsource(canonical_scientific_payload_bytes)
    )


def test_unsorted_call_shape_mutant_fails_the_same_source_helper():
    source = inspect.getsource(canonical_scientific_payload_bytes)
    with pytest.raises(AssertionError):
        _assert_sorted_serialization_call(
            lambda: source.replace("sort_keys=True", "sort_keys=False")
        )


def test_precision_loss_unsorted_and_inventory_mutants_fail_the_canonical_helper():
    def lossy(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        for member in mapping["quartet_members"]:
            member["p_value_hex"] = str(float.fromhex(member["p_value_hex"]))
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    def unsorted(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        reversed_mapping = dict(reversed(tuple(mapping.items())))
        return json.dumps(reversed_mapping, sort_keys=False, separators=(",", ":")).encode()

    def drops_retained(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        for member in mapping["quartet_members"]:
            member.pop("retained_regions")
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    def drops_co_maximal(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        for member in mapping["quartet_members"]:
            member.pop("co_maximal_regions")
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    def adds_host_telemetry(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        mapping["host_telemetry"] = [["host", "mutable"]]
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    calls = 0

    def nondeterministic(payload):
        nonlocal calls
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        calls += 1
        mapping["unstable_attempt"] = calls
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    def adds_cross_member_summary(payload):
        mapping = results_module._scientific_mapping(validate_scientific_payload(payload))
        mapping["minimum_p_value"] = "forbidden-field-sentinel"
        return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()

    for mutant in (
        lossy,
        unsorted,
        drops_retained,
        drops_co_maximal,
        adds_host_telemetry,
        nondeterministic,
        adds_cross_member_summary,
    ):
        with pytest.raises(AssertionError):
            _assert_canonical_contract(mutant, scientific_payload_hash)


def test_sealed_result_detects_payload_or_hash_mutation():
    payload = _payload()
    result = seal_scientific_payload(payload)
    assert isinstance(result, CalibrationReplicationResult)
    assert result.scientific_payload_hash == scientific_payload_hash(payload)
    with pytest.raises(SpineError, match="payload hash differs"):
        CalibrationReplicationResult(payload, "0" * 64)
    with pytest.raises(SpineError, match="payload hash differs"):
        replace(result, scientific_payload=replace(payload, code_identity="changed"))
