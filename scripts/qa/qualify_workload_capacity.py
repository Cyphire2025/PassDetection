"""Run the declared workload against its fixed local qualification stack.

Focused contract, observation, traffic and resource owners retain the original
public function aliases; this module retains the original command entry point.
It accepts no target, credential or budget overrides.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess as subprocess

from workload_capacity_contract import (
    API_MEMORY_BYTES as API_MEMORY_BYTES,
)
from workload_capacity_contract import (
    BUDGETS_MS as BUDGETS_MS,
)
from workload_capacity_contract import (
    EXPECTED_SCAN_REQUESTS as EXPECTED_SCAN_REQUESTS,
)
from workload_capacity_contract import (
    EXPECTED_SECONDS as EXPECTED_SECONDS,
)
from workload_capacity_contract import (
    EXPECTED_UNIQUE_SCANS as EXPECTED_UNIQUE_SCANS,
)
from workload_capacity_contract import (
    FIXTURES as FIXTURES,
)
from workload_capacity_contract import (
    MAX_PENDING_AGE_SECONDS as MAX_PENDING_AGE_SECONDS,
)
from workload_capacity_contract import (
    OBSERVATION_SECONDS as OBSERVATION_SECONDS,
)
from workload_capacity_contract import (
    OBSERVED_QUEUES as OBSERVED_QUEUES,
)
from workload_capacity_contract import (
    ORIGIN as ORIGIN,
)
from workload_capacity_contract import (
    OVERLOAD_BUDGET_MS as OVERLOAD_BUDGET_MS,
)
from workload_capacity_contract import (
    OVERLOAD_SECONDS as OVERLOAD_SECONDS,
)
from workload_capacity_contract import (
    RECOVERY_DEADLINE_SECONDS as RECOVERY_DEADLINE_SECONDS,
)
from workload_capacity_contract import (
    RECOVERY_SECONDS as RECOVERY_SECONDS,
)
from workload_capacity_gates import (
    gates as gates,
)
from workload_capacity_gates import (
    observed_queue_drain_seconds as observed_queue_drain_seconds,
)
from workload_capacity_measurements import (
    begin_stage as begin_stage,
)
from workload_capacity_measurements import (
    end_stage as end_stage,
)
from workload_capacity_measurements import (
    measured as measured,
)
from workload_capacity_measurements import (
    percentile as percentile,
)
from workload_capacity_measurements import (
    summarize as summarize,
)
from workload_capacity_resources import (
    fixture as fixture,
)
from workload_capacity_resources import (
    inspect_backend as inspect_backend,
)
from workload_capacity_run import main as main
from workload_capacity_traffic import (
    overload_actor as overload_actor,
)
from workload_capacity_traffic import (
    paced_actor as paced_actor,
)
from workload_capacity_traffic import (
    path_for as path_for,
)
from workload_capacity_traffic import (
    scans as scans,
)
from workload_capacity_traffic import (
    synthetic_jpeg as synthetic_jpeg,
)
from workload_capacity_traffic import (
    tenant_negatives as tenant_negatives,
)
from workload_capacity_traffic import (
    uploads as uploads,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    raise SystemExit(asyncio.run(main()))
