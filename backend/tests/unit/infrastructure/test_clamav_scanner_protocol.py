"""ClamD replies must be complete verdicts, not partial TCP reads or substrings."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest

from app.infrastructure.security import upload_validator
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)


def _socket(monkeypatch: pytest.MonkeyPatch, replies: list[bytes]) -> MagicMock:
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.recv.side_effect = replies
    monkeypatch.setattr(upload_validator.socket, "create_connection", lambda *_a, **_k: sock)
    return sock


def _scanner() -> ClamAVMalwareScanner:
    return ClamAVMalwareScanner(host="scanner.test", port=3310, timeout_seconds=1.0)


def test_fragmented_clean_verdict_scans_exact_original_stream(monkeypatch) -> None:
    sock = _socket(monkeypatch, [b"str", b"eam: O", b"K", b"\0"])
    content = b"original PDF bytes" * 1500

    _scanner().scan(content)

    sent = [call.args[0] for call in sock.sendall.call_args_list]
    assert sent[0] == b"zINSTREAM\0"
    assert sent[-1] == struct.pack("!I", 0)
    assert all(struct.unpack("!I", chunk[:4])[0] == len(chunk[4:]) for chunk in sent[1:-1])
    assert b"".join(chunk[4:] for chunk in sent[1:-1]) == content
    assert sock.recv.call_count == 4


@pytest.mark.parametrize(
    "replies", [[b"stream: Test-Signature FOUND\0"], [b"stream: Test-", b"Signature FOUND\0"]]
)
def test_positive_signature_verdict_is_a_rejection(monkeypatch, replies) -> None:
    _socket(monkeypatch, replies)
    with pytest.raises(MalwareScanRejectedError):
        _scanner().scan(b"synthetic bytes")


@pytest.mark.parametrize(
    "replies",
    [
        [b"INSTREAM size limit exceeded. ERROR\0"],
        [b"stream: engine unavailable ERROR\0"],
        [b"stream: NOT OK\0"],
        [b"stream: BROKEN\0"],
        [b"stream: signature FOUND ERROR\0"],
        [b"OK\0"],
        [b"stream: OK", b""],
        [b"stream: Test-Signature FOUND", b""],
        [b""],
        [b"stream: OK\0unexpected"],
        [b"stream: OK\0stream: bad FOUND\0"],
        [b"x" * 4096],
    ],
)
def test_error_unknown_or_incomplete_reply_is_unavailable_not_infected(
    monkeypatch, replies
) -> None:
    _socket(monkeypatch, replies)
    with pytest.raises(MalwareScannerUnavailableError):
        _scanner().scan(b"synthetic bytes")


def test_socket_failure_is_unavailable(monkeypatch) -> None:
    sock = _socket(monkeypatch, [])
    sock.recv.side_effect = TimeoutError("scanner socket timeout")
    with pytest.raises(MalwareScannerUnavailableError):
        _scanner().scan(b"synthetic bytes")


def test_fragmented_response_still_obeys_total_deadline(monkeypatch) -> None:
    sock = _socket(monkeypatch, [b"stream:", b" OK\0"])
    # Start, command, content, terminator, first read, expired second read.
    monkeypatch.setattr(
        upload_validator.time, "monotonic", MagicMock(side_effect=[0, 0, 0, 0, 0, 2])
    )
    with pytest.raises(MalwareScannerUnavailableError):
        _scanner().scan(b"synthetic bytes")
    assert sock.recv.call_count == 1
