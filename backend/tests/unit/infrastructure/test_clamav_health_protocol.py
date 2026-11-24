"""A health reply is also a bounded NUL-framed TCP message."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.infrastructure.security import upload_validator
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner,
    MalwareScannerConfigurationError,
    assert_malware_scanner_ready,
)


def _socket(monkeypatch, replies):
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.recv.side_effect = replies
    monkeypatch.setattr(
        upload_validator.socket, "create_connection", lambda *_args, **_kwargs: sock
    )
    return sock


@pytest.mark.parametrize(
    "replies", [[b"PONG\0"], [b"PO", b"NG\0"], [b"P", b"O", b"N", b"G", b"\0"], [b" PONG\r\n\0"]]
)
def test_complete_health_frame_handles_tcp_fragmentation(monkeypatch, replies):
    sock = _socket(monkeypatch, replies)
    ClamAVMalwareScanner(host="synthetic.test", port=3310, timeout_seconds=1).healthcheck()
    sock.sendall.assert_called_once_with(b"zPING\0")
    assert sock.recv.call_count == len(replies)
    received = 0
    for read, reply in zip(sock.recv.call_args_list, replies, strict=True):
        assert read.args == (64 - received,)
        received += len(reply)
    sock.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "replies",
    [
        [b"PONG", b""],
        [b""],
        [b"x" * 64],
        [b"PONG\0extra"],
        [b"PONG\0PONG\0"],
        [b"PANG\0"],
        [b"\xff\0"],
    ],
)
def test_incomplete_unknown_oversized_or_extra_health_frames_fail_closed(monkeypatch, replies):
    sock = _socket(monkeypatch, replies)
    with pytest.raises(MalwareScannerConfigurationError):
        ClamAVMalwareScanner(host="synthetic.test", port=3310, timeout_seconds=1).healthcheck()
    sock.__exit__.assert_called_once()


def test_fragmented_health_read_shares_one_total_timeout(monkeypatch):
    sock = _socket(monkeypatch, [])
    now = [0.0]

    def first_fragment(_maximum):
        now[0] = 2.0
        return b"PO"

    sock.recv.side_effect = first_fragment
    monkeypatch.setattr(upload_validator.time, "monotonic", lambda: now[0])
    with pytest.raises(MalwareScannerConfigurationError):
        ClamAVMalwareScanner(host="synthetic.test", port=3310, timeout_seconds=1).healthcheck()
    assert sock.recv.call_count == 1


@pytest.mark.parametrize("stage", ["connect", "send", "receive"])
def test_socket_failures_keep_configuration_error_surface_and_release_socket(monkeypatch, stage):
    sock = _socket(monkeypatch, [b"PONG\0"])
    failure = OSError("synthetic daemon failure")
    if stage == "connect":
        monkeypatch.setattr(
            upload_validator.socket, "create_connection", MagicMock(side_effect=failure)
        )
    elif stage == "send":
        sock.sendall.side_effect = failure
    else:
        sock.recv.side_effect = failure

    with pytest.raises(MalwareScannerConfigurationError) as raised:
        ClamAVMalwareScanner(host="synthetic.test", port=3310, timeout_seconds=1).healthcheck()
    assert raised.value.__cause__ is failure
    assert "synthetic daemon failure" not in str(raised.value)
    assert sock.__exit__.call_count == (0 if stage == "connect" else 1)


def test_connect_time_is_included_in_health_deadline(monkeypatch):
    sock = _socket(monkeypatch, [b"PONG\0"])
    now = [0.0]

    def connect(_address, *, timeout):
        assert timeout == 1
        now[0] = 2.0
        return sock

    monkeypatch.setattr(upload_validator.socket, "create_connection", connect)
    monkeypatch.setattr(upload_validator.time, "monotonic", lambda: now[0])
    with pytest.raises(MalwareScannerConfigurationError):
        ClamAVMalwareScanner(host="synthetic.test", port=3310, timeout_seconds=1).healthcheck()
    sock.sendall.assert_not_called()
    sock.recv.assert_not_called()
    sock.__exit__.assert_called_once()


@pytest.mark.parametrize("replies", [[b"PO", b"NG\0"], [b"PONG", b""]])
def test_production_readiness_uses_framed_health_result(monkeypatch, replies):
    sock = _socket(monkeypatch, replies)
    settings = SimpleNamespace(
        is_development=False,
        untrusted_document_ingestion_enabled=True,
        malware_scanner_enabled=True,
        malware_scanner_host="synthetic.test",
        malware_scanner_port=3310,
        malware_scanner_timeout_seconds=1,
    )
    if replies[-1] == b"":
        with pytest.raises(MalwareScannerConfigurationError):
            assert_malware_scanner_ready(settings)
    else:
        assert_malware_scanner_ready(settings)
    sock.__exit__.assert_called_once()
