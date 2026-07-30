"""One-shot Phase 5 v2 coverage calibration runner.

This script is intentionally outside both ``tests/`` and ``mnq_lab/``. Importing
it constructs no random generator and consumes no registered seed stream.
Execute it only once, after the required independent static audit.
"""

from __future__ import annotations

import json

import numpy as np

from mnq_lab.constants import load_bootstrap_constants
from mnq_lab.core.bootstrap import (
    bootstrap_weighted_quantile_replicates,
    percentile_interval,
)
from mnq_lab.core.weights import session_equal_weights

CALIBRATION_ROOT_ENTROPY = 282152804769136717845935072558193670437
CALIBRATION_REPLICATIONS = 3000
SESSION_COUNT = 80
ROWS_PER_SESSION = 4
BOOTSTRAP_DRAWS = 999
CONFIDENCE_LEVEL = 0.95


def main() -> None:
    mean_block_groups = load_bootstrap_constants()[
        "mean_block_sessions_primary"
    ]
    group_ids = np.repeat(
        np.arange(SESSION_COUNT, dtype=np.int64),
        ROWS_PER_SESSION,
    )
    baseline_weights, _ = session_equal_weights(group_ids)
    eligibility = np.ones(group_ids.size, dtype=bool)
    outer_sequences = np.random.SeedSequence(
        CALIBRATION_ROOT_ENTROPY
    ).spawn(CALIBRATION_REPLICATIONS)
    coverage_count = 0

    for outer_sequence in outer_sequences:
        data_sequence, bootstrap_sequence = outer_sequence.spawn(2)
        data_rng = np.random.Generator(np.random.PCG64(data_sequence))
        bootstrap_rng = np.random.Generator(
            np.random.PCG64(bootstrap_sequence)
        )
        session_values = data_rng.standard_normal(SESSION_COUNT)
        values = np.repeat(session_values, ROWS_PER_SESSION)
        replicates = bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline_weights,
            (values,),
            (eligibility,),
            (0.5,),
            BOOTSTRAP_DRAWS,
            mean_block_groups,
            bootstrap_rng,
        )[0]
        lower, upper = percentile_interval(
            replicates,
            CONFIDENCE_LEVEL,
        )
        coverage_count += int(lower <= 0.0 <= upper)

    evidence = {
        "covered": coverage_count,
        "replications": CALIBRATION_REPLICATIONS,
        "p_hat": f"{coverage_count}/{CALIBRATION_REPLICATIONS}",
    }
    print("PHASE5_COVERAGE_CALIBRATION=" + json.dumps(evidence))


if __name__ == "__main__":
    main()
