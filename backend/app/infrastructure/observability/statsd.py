"""Bounded, low-cardinality StatsD export for cross-process metrics."""

from __future__ import annotations

import math
import re
import socket
from threading import RLock
from typing import Any

from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.infrastructure.observability.metrics import MetricsRegistry, metrics

logger = get_logger(__name__)

_EXPORT_SNAPSHOT_NAME = "statsd_export"
_INVALID_METRIC_CHARACTERS = re.compile(r"[^A-Za-z0-9_.]+")
_REPEATED_SEPARATORS = re.compile(r"[._]{2,}")
_MAX_METRIC_NAME_BYTES = 240
_MAX_DATAGRAM_BYTES = 512


class StatsdMetricsExporter:
    """Best-effort UDP exporter with bounded datagrams and no business labels."""

    def __init__(self, *, host: str, port: int, namespace: str) -> None:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        if not addresses:
            raise OSError("StatsD host did not resolve")
        family, socket_type, protocol, _canonical_name, address = addresses[0]
        self._socket = socket.socket(family, socket_type, protocol)
        self._socket.setblocking(False)
        self._address: Any = address
        self._namespace = self._metric_name(namespace)
        self._sent = 0
        self._dropped = 0
        self._closed = False
        self._lock = RLock()

    @staticmethod
    def _metric_name(value: str) -> str:
        normalized = _INVALID_METRIC_CHARACTERS.sub("_", value.strip())
        normalized = _REPEATED_SEPARATORS.sub("_", normalized).strip("._")
        encoded = normalized.encode("ascii", errors="ignore")[:_MAX_METRIC_NAME_BYTES]
        result = encoded.decode("ascii").strip("._")
        return result or "unnamed"

    def _send(self, name: str, value: int | float, metric_type: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            with self._lock:
                self._dropped += 1
            return
        metric_name = self._metric_name(f"{self._namespace}.{name}")
        payload = f"{metric_name}:{value:.10g}|{metric_type}".encode("ascii")
        if len(payload) > _MAX_DATAGRAM_BYTES:
            with self._lock:
                self._dropped += 1
            return
        with self._lock:
            if self._closed:
                self._dropped += 1
                return
            try:
                self._socket.sendto(payload, self._address)
            except (BlockingIOError, OSError):
                self._dropped += 1
            else:
                self._sent += 1

    def increment(self, name: str, amount: int = 1) -> None:
        self._send(name, amount, "c")

    def observe(self, name: str, value: float) -> None:
        self._send(name, value, "h")

    def set_gauge(self, name: str, value: float) -> None:
        self._send(name, value, "g")

    def snapshot(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "status": "closed" if self._closed else "configured",
                "transport": "udp",
                "sent": self._sent,
                "dropped": self._dropped,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._socket.close()


def configure_metrics_export(
    settings: Settings,
    *,
    registry: MetricsRegistry = metrics,
) -> None:
    """Configure one exporter per API/worker process from validated settings."""

    registry.close_export_sink()
    registry.unregister_snapshot_provider(_EXPORT_SNAPSHOT_NAME)
    if settings.metrics_exporter == "disabled":
        return
    try:
        exporter = StatsdMetricsExporter(
            host=settings.metrics_statsd_host,
            port=settings.metrics_statsd_port,
            namespace=settings.metrics_namespace,
        )
    except OSError as exc:
        if settings.metrics_export_required:
            raise RuntimeError("Required StatsD exporter could not be initialized") from exc
        logger.warning(
            "statsd_metrics_export_unavailable",
            error_type=type(exc).__name__,
        )
        return
    registry.configure_export_sink(exporter)
    registry.register_snapshot_provider(_EXPORT_SNAPSHOT_NAME, exporter.snapshot)
