"""Reviewed fixed QA workload, acceptance budgets and subprocess command."""

from mcp_capacity import MCP_BUDGETS_MS
from run_qualification_stack import COMPOSE

ORIGIN = "https://localhost:58443"

FIXTURES = [
    *COMPOSE,
    "exec",
    "-T",
    "backend",
    "python",
    "/workspace/scripts/qa/capacity_fixtures.py",
]

BUDGETS_MS = {
    **MCP_BUDGETS_MS,
    "stats": (750, 1500),
    "notifications": (500, 1000),
    "search": (1000, 2000),
    "roster": (1500, 3000),
    "scan": (1000, 2000),
    "upload": (8000, 15000),
}

EXPECTED_SECONDS = 60

OVERLOAD_SECONDS = 15

RECOVERY_SECONDS = 30

OBSERVATION_SECONDS = 220

OVERLOAD_BUDGET_MS = (2000, 5000)

MAX_PENDING_AGE_SECONDS = 900

RECOVERY_DEADLINE_SECONDS = 300

EXPECTED_SCAN_REQUESTS = 60

EXPECTED_UNIQUE_SCANS = 30

OBSERVED_QUEUES = ("passport_ocr", "ecr_checks")

API_MEMORY_BYTES = 2560 * 1024**2
