"""Ratification-gated Phase 8 bootstrap throughput benchmark; prints no result."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time

import numpy as np

from mnq_lab.constants import REPO_ROOT
from mnq_lab.core.weights import session_equal_weights
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import (
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    distinct_bootstrap_evaluations,
    joint_bootstrap_intervals,
)


def _column(root, manifest, table_root, name):
    return np.load(
        root / table_root / manifest["columns"][name]["file"],
        mmap_mode="r",
        allow_pickle=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", type=int, default=16)
    args = parser.parse_args()
    if args.terms <= 0:
        raise SystemExit("--terms must be positive")

    root = REPO_ROOT / "data/exploration/derived/phase7-unit-o-first-run-v1"
    require_ratified_unit_o(root)
    unit = json.loads((root / "unit_o/manifest.json").read_text(encoding="utf-8"))
    phase7 = json.loads((root / "phase7/manifest.json").read_text(encoding="utf-8"))
    assignments = phase7["tables"]["assignments"]
    unit_column = lambda name: _column(root, unit, "unit_o", name)
    assignment_column = lambda name: _column(
        root, assignments, "phase7", name
    )

    unit_mask = (unit_column("estimand") == "fully_labeled_1m_grid") & (
        unit_column("horizon_minutes") == 30
    )
    assignment_mask = (
        assignment_column("arm_id") == "primary_ewma78_permissive_expanding"
    )
    groups = np.asarray(unit_column("session_id")[unit_mask])
    base_values = np.asarray(
        unit_column("downward_excursion_ticks")[unit_mask], dtype=np.int32
    )
    if not (
        np.array_equal(
            groups, np.asarray(assignment_column("session_id")[assignment_mask])
        )
        and np.array_equal(
            np.asarray(unit_column("ts_event_ns")[unit_mask]),
            np.asarray(assignment_column("ts_event_ns")[assignment_mask]),
        )
        and np.array_equal(
            np.asarray(unit_column("tau_ns")[unit_mask]),
            np.asarray(assignment_column("tau_ns")[assignment_mask]),
        )
    ):
        raise RuntimeError("Unit O and Phase 7 benchmark keys differ")
    eligible = (
        np.asarray(unit_column("outcome_valid")[unit_mask], dtype=np.bool_)
        & (
            np.asarray(assignment_column("session_phase")[assignment_mask])
            == "midday"
        )
        & (
            np.asarray(assignment_column("category_name")[assignment_mask])
            == "mid"
        )
    )
    weights = np.zeros(groups.size, dtype=np.float64)
    local_weights, diagnostics = session_equal_weights(groups[eligible])
    weights[eligible] = local_weights
    ok = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    terms = []
    requests = []
    for term_index in range(args.terms):
        values = (base_values.astype(np.int64) + term_index).astype(np.int32)
        for statistic in ("q50", "q75", "q90"):
            term_id = f"benchmark-{term_index}-{statistic}"
            terms.append(
                BootstrapQuantileTerm(
                    term_id, values, eligible, weights, statistic
                )
            )
            requests.append(
                BootstrapIntervalRequest(
                    f"benchmark-request-{term_index}-{statistic}",
                    term_id,
                    None,
                    ok,
                )
            )
    terms = tuple(terms)
    requests = tuple(requests)
    started = time.perf_counter()
    result = joint_bootstrap_intervals(groups, terms, requests)
    elapsed = time.perf_counter() - started
    if len(result.requests) != len(requests) or any(
        len(request.intervals) != 4 for request in result.requests
    ):
        raise RuntimeError("benchmark output shape differs")
    print(
        f"distinct_evaluations={distinct_bootstrap_evaluations(terms)} "
        f"elapsed_seconds={elapsed:.6f}"
    )
    print(
        f"n_anchors={int(np.count_nonzero(eligible))} "
        f"n_sessions={diagnostics.contributing_group_count} "
        f"weight_ess={diagnostics.weight_ess:.12f}"
    )
    print(
        f"logical_cores={os.cpu_count()} machine={platform.processor()} "
        f"platform={platform.platform()}"
    )


if __name__ == "__main__":
    main()
