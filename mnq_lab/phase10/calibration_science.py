"""Concrete one-replication calibration computation, callable only by the runner."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import canonical_json_bytes
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.calibration_controls import plant_frozen_effect_ladder
from mnq_lab.phase10.calibration_entropy import (
    CALIBRATION_ROOT_LABEL,
    CALIBRATION_ROOT_SHA256,
)
from mnq_lab.phase10.calibration_orchestration import (
    WorkerEnvironmentIdentity,
    build_verified_outer_control,
    fresh_internal_mappings,
)
from mnq_lab.phase10.calibration_results import (
    QUARTET_MEMBERS,
    REJECTION_RULE_IDENTITY,
    QuartetMemberResult,
    ReplicationScientificPayload,
    exact_co_maximal_regions,
    localization_overlap,
    rejection_event,
    seal_scientific_payload,
)
from mnq_lab.phase10.contract import PERMUTATION_POPULATION, load_phase10_contract
from mnq_lab.phase10.evaluation import RawSurfaceEvaluation, evaluate_primary_surface
from mnq_lab.phase10.mapping import apply_joint_mapping
from mnq_lab.phase10.pvalue import permutation_pvalue
from mnq_lab.phase10.surface import coherence_statistic, shared_standardization


def _identity_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _member_statuses(evaluation: RawSurfaceEvaluation) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value) for value in np.asarray(evaluation.statuses).reshape(-1))
    )


def compute_calibration_replication(
    corpus: FormalCorpus,
    replication_index: int,
    attempt_lineage: tuple[str, ...],
    classified_failures: tuple[str, ...],
    environment: WorkerEnvironmentIdentity,
    permutation_count: int,
):
    """Evaluate one complete quartet with its own verified control and ensemble."""
    if (
        isinstance(permutation_count, bool)
        or not isinstance(permutation_count, int)
        or permutation_count <= 0
    ):
        raise SpineError("calibration permutation count must be a positive built-in integer")
    contract = load_phase10_contract()
    control = build_verified_outer_control(corpus, replication_index)
    effects = plant_frozen_effect_ladder(corpus, control)
    member_corpora = (
        corpus,
        *(replace(corpus, downward_excursion_ticks=effect.outcomes) for effect in effects),
    )
    observed = tuple(
        evaluate_primary_surface(member_corpus, control.state_codes, control.state_valid)
        for member_corpus in member_corpora
    )
    mappings = fresh_internal_mappings(
        corpus,
        replication_index,
        permutation_count,
    )
    null_contrasts = tuple(
        np.zeros((permutation_count, *item.contrasts.shape), dtype=np.int64)
        for item in observed
    )
    null_valid = tuple(
        np.zeros((permutation_count, *item.valid.shape), dtype=np.bool_)
        for item in observed
    )
    null_yearly = tuple(
        np.zeros((permutation_count, *item.yearly_contrasts.shape), dtype=np.int64)
        for item in observed
    )
    null_yearly_valid = tuple(
        np.zeros((permutation_count, *item.yearly_valid.shape), dtype=np.bool_)
        for item in observed
    )
    for mapping_index, mapping in enumerate(mappings):
        reassigned = apply_joint_mapping(
            control.state_codes,
            control.state_valid,
            (corpus.outcome_valid, corpus.window_fits_rth),
            mapping,
        )
        for member_index, member_corpus in enumerate(member_corpora):
            evaluated = evaluate_primary_surface(
                member_corpus,
                reassigned.state_codes,
                reassigned.state_valid,
            )
            null_contrasts[member_index][mapping_index] = evaluated.contrasts
            null_valid[member_index][mapping_index] = evaluated.valid
            null_yearly[member_index][mapping_index] = evaluated.yearly_contrasts
            null_yearly_valid[member_index][mapping_index] = evaluated.yearly_valid

    members: list[QuartetMemberResult] = []
    magnitudes = (0, *(effect.magnitude_ticks for effect in effects))
    all_statuses: list[str] = []
    for member_index, (name, magnitude) in enumerate(
        zip(QUARTET_MEMBERS, magnitudes, strict=True)
    ):
        standardized = shared_standardization(
            observed[member_index].contrasts,
            observed[member_index].valid,
            null_contrasts[member_index],
            null_valid[member_index],
        )
        surface = coherence_statistic(
            standardized.observed_z,
            standardized.observed_valid,
            observed[member_index].yearly_contrasts,
            observed[member_index].yearly_valid,
        )
        null_statistics = np.empty(permutation_count, dtype=np.float64)
        for mapping_index in range(permutation_count):
            null_statistics[mapping_index] = coherence_statistic(
                standardized.null_z[mapping_index],
                standardized.null_valid[mapping_index],
                null_yearly[member_index][mapping_index],
                null_yearly_valid[member_index][mapping_index],
            ).value
        p_value = permutation_pvalue(surface.value, null_statistics)
        rejected = rejection_event(p_value)
        co_maximal = exact_co_maximal_regions(surface)
        overlap = None if name == "null" else localization_overlap(surface, rejected).overlap
        statuses = _member_statuses(observed[member_index])
        all_statuses.extend(statuses)
        members.append(
            QuartetMemberResult(
                member=name,
                effect_magnitude_ticks=magnitude,
                p_value=p_value,
                rejected=rejected,
                observed_statistic=surface.value,
                retained_regions=surface.regions,
                co_maximal_regions=co_maximal,
                localization_overlap=overlap,
                structural_statuses=statuses,
                classified_failures=classified_failures,
            )
        )

    environment_hash = _identity_hash(asdict(environment))
    worker_hash = _identity_hash(
        {
            "process_start_method": environment.process_start_method,
            "process_thread_settings": environment.process_thread_settings,
            "worker_count": environment.worker_count,
        }
    )
    payload = ReplicationScientificPayload(
        replication_index=replication_index,
        calibration_root_label=CALIBRATION_ROOT_LABEL,
        calibration_root_digest=CALIBRATION_ROOT_SHA256,
        control_spawn_key=(replication_index, 0),
        ensemble_spawn_key=(replication_index, 1),
        completion_state="complete",
        attempt_lineage=attempt_lineage,
        permutations=permutation_count,
        rejection_rule_identity=REJECTION_RULE_IDENTITY,
        formal_population_identity=PERMUTATION_POPULATION,
        weighting_planes=contract.weighting_planes,
        quartet_members=tuple(members),
        structural_statuses=tuple(dict.fromkeys(all_statuses)),
        classified_failures=classified_failures,
        code_identity=environment.repository_commit,
        package_identity=environment.package_lock_sha256,
        corpus_identity=environment.corpus_manifest_sha256,
        environment_identity=environment_hash,
        worker_configuration_identity=worker_hash,
    )
    return seal_scientific_payload(payload)
