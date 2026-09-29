"""The minimum deployed MCP envelope, independent of fixture credentials."""

import uuid

SOURCE_ROWS = 100
SOURCE_BYTES = 1024 * 1024
EXPORT_FAMILIES = ("passport_excel",)
CAPABILITIES = frozenset({"mcp:read", "mcp:export"})
EXPORT_SCHEDULING = "serialized_per_stage_including_wait_in_latency"


def require_minimum_profile(*, enabled, capabilities, families, rows, byte_limit):
    if (enabled is not True or set(capabilities) != CAPABILITIES
            or set(families) != set(EXPORT_FAMILIES)
            or type(rows) is not int or rows != SOURCE_ROWS
            or type(byte_limit) is not int or byte_limit != SOURCE_BYTES):
        raise ValueError("Capacity lane requires passport_excel/100 source rows/1MiB/read+export")


def export_selection(run_id: str, group: dict) -> dict:
    count = group["group_size"]
    if type(count) is not int or count < 1:
        raise ValueError("Synthetic group requires a positive retained row count")
    size = min(count, SOURCE_ROWS)
    return {
        "export_size": size,
        "export_submission_ids": [
            str(uuid.uuid5(uuid.UUID(run_id), f"passenger-{group['tenant']}-{index}"))
            for index in range(size)
        ] if count > SOURCE_ROWS else [],
    }
