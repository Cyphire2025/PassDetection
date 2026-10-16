from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.documents import pdf_parser_memory as memory


@pytest.mark.parametrize(
    ("remaining_mib", "expected"), [(2048, 8), (1920, 8), (1280, 5), (448, 1), (400, 0)]
)
def test_workers_scale_down_as_container_headroom_shrinks(monkeypatch, remaining_mib, expected):
    monkeypatch.setattr(
        memory,
        "memory_snapshot",
        lambda: memory.PdfMemorySnapshot(remaining_mib * memory.MIB, 8 * 1024 * memory.MIB),
    )
    assert memory.affordable_processes(8, 0, required=True) == expected


def test_host_reserve_and_source_serialization_are_budgeted(monkeypatch):
    monkeypatch.setattr(
        memory,
        "memory_snapshot",
        lambda: memory.PdfMemorySnapshot(2048 * memory.MIB, 2500 * memory.MIB),
    )
    assert memory.affordable_processes(8, 0, required=True) == 1
    assert memory.affordable_processes(8, 16 * memory.MIB, required=True) == 0


def test_pressure_threshold_stops_before_container_or_host_reserve_exhaustion(monkeypatch):
    for snapshot in [
        memory.PdfMemorySnapshot(159 * memory.MIB, 8 * 1024 * memory.MIB),
        memory.PdfMemorySnapshot(2048 * memory.MIB, 2207 * memory.MIB),
    ]:
        monkeypatch.setattr(memory, "memory_snapshot", lambda snapshot=snapshot: snapshot)
        assert memory.memory_under_pressure()


def test_linux_reads_actual_cgroup_charge_and_available_host_memory(monkeypatch):
    monkeypatch.setattr(memory.sys, "platform", "linux")
    values = {
        "/sys/fs/cgroup/memory.max": str(3584 * memory.MIB),
        "/sys/fs/cgroup/memory.current": str(1536 * memory.MIB),
        "/proc/meminfo": "MemAvailable: 8388608 kB\n",
    }
    monkeypatch.setattr(Path, "read_text", lambda path: values[str(path).replace("\\", "/")])
    snapshot = memory.memory_snapshot()
    assert snapshot == memory.PdfMemorySnapshot(2048 * memory.MIB, 8 * 1024 * memory.MIB)


def test_missing_production_linux_memory_accounting_defers_checks(monkeypatch):
    monkeypatch.setattr(memory.sys, "platform", "linux")
    monkeypatch.setattr(memory, "memory_snapshot", lambda: None)
    assert memory.affordable_processes(8, 0, required=True) == 0
    assert memory.affordable_processes(8, 0, required=False) == 8
