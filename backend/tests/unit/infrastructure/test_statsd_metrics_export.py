from __future__ import annotations

from typing import Any

from app.infrastructure.observability.metrics import MetricsRegistry
from app.infrastructure.observability.statsd import StatsdMetricsExporter


class _FakeSocket:
    def __init__(self) -> None:
        self.datagrams: list[tuple[bytes, object]] = []
        self.blocking: bool | None = None
        self.closed = False
        self.fail = False

    def setblocking(self, value: bool) -> None:
        self.blocking = value

    def sendto(self, payload: bytes, address: object) -> int:
        if self.fail:
            raise OSError("collector unavailable")
        self.datagrams.append((payload, address))
        return len(payload)

    def close(self) -> None:
        self.closed = True


def _exporter(monkeypatch: Any) -> tuple[StatsdMetricsExporter, _FakeSocket]:
    fake_socket = _FakeSocket()
    monkeypatch.setattr(
        "app.infrastructure.observability.statsd.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 2, 17, "", ("127.0.0.1", 9125))],
    )
    monkeypatch.setattr(
        "app.infrastructure.observability.statsd.socket.socket",
        lambda *_args, **_kwargs: fake_socket,
    )
    return (
        StatsdMetricsExporter(
            host="metrics-exporter",
            port=9125,
            namespace="passdetection",
        ),
        fake_socket,
    )


def test_registry_exports_counters_histograms_and_gauges_without_payload_labels(
    monkeypatch: Any,
) -> None:
    exporter, fake_socket = _exporter(monkeypatch)
    registry = MetricsRegistry()
    registry.configure_export_sink(exporter)

    registry.increment("http.requests.total.GET.200.api_v1_health_ready", 2)
    registry.observe("http.requests.duration_ms.GET.api_v1_health_ready", 12.5)
    registry.set_gauge("database.pool.checked_out", 3)

    assert fake_socket.blocking is False
    assert [payload for payload, _address in fake_socket.datagrams] == [
        b"passdetection.http.requests.total.GET.200.api_v1_health_ready:2|c",
        b"passdetection.http.requests.duration_ms.GET.api_v1_health_ready:12.5|h",
        b"passdetection.database.pool.checked_out:3|g",
    ]
    assert exporter.snapshot() == {
        "status": "configured",
        "transport": "udp",
        "sent": 3,
        "dropped": 0,
    }


def test_export_failure_is_counted_and_never_changes_the_local_metric(
    monkeypatch: Any,
) -> None:
    exporter, fake_socket = _exporter(monkeypatch)
    registry = MetricsRegistry()
    registry.configure_export_sink(exporter)
    fake_socket.fail = True

    registry.increment("attendance.events.accepted")

    assert registry.snapshot()["counters"] == {"attendance.events.accepted": 1}
    assert exporter.snapshot()["dropped"] == 1


def test_metric_names_and_non_finite_values_fail_bounded(
    monkeypatch: Any,
) -> None:
    exporter, fake_socket = _exporter(monkeypatch)

    exporter.increment("route.{tenant-id}.accepted")
    exporter.observe("provider.duration", float("nan"))
    exporter.close()
    exporter.increment("after.close")

    assert fake_socket.datagrams[0][0] == b"passdetection.route_tenant_id_accepted:1|c"
    assert exporter.snapshot() == {
        "status": "closed",
        "transport": "udp",
        "sent": 1,
        "dropped": 2,
    }
    assert fake_socket.closed is True
