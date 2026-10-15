"""Require the reviewed CPython security release and probe in-memory TLS guards."""
from __future__ import annotations

import ssl
import sys


def require_patched_python(version: tuple[int, ...]) -> None:
    # This runtime's extensions are built from the matching 3.11 sources.
    if version[:2] != (3, 11) or version[:3] < (3, 11, 17):
        raise RuntimeError("Runtime requires reviewed CPython 3.11.17 or a later 3.11 security release")


def probe_python_security() -> dict[str, str | int]:
    require_patched_python(tuple(sys.version_info[:3]))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # CVE-2026-19553: server-side MemoryBIO must reject client-only arguments.
    # No sockets, credentials, certificates or external service are required.
    for arguments in ({"server_hostname": "example.invalid"}, {"session": object()}):
        try:
            context.wrap_bio(ssl.MemoryBIO(), ssl.MemoryBIO(), server_side=True, **arguments)
        except ValueError:
            pass
        else:
            raise RuntimeError("Server-side TLS accepted a client-only argument")
    return {"python": ".".join(map(str, sys.version_info[:3])), "ssl_wrap_bio_argument_negatives": 2}
