"""Privacy-bounded extraction of link hosts from untrusted email text."""

from __future__ import annotations

import re

_URL_PATTERN = re.compile(
    r"https?://([A-Za-z0-9.-]+)(?::\d+)?(?:[/?#][^\s<>]*)?",
    re.IGNORECASE,
)


def safe_link_hosts(body: str) -> list[str]:
    """Return at most 20 normalized hosts without retaining URL paths."""

    hosts: list[str] = []
    for match in _URL_PATTERN.finditer(body[:8_000]):
        host = match.group(1).casefold().rstrip(".")[:253]
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= 20:
            break
    return hosts
