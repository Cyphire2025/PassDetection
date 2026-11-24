"""Load the exact, separately reviewed source bindings without widening admission."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

_MAXIMUM_BYTES = 256 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"path", "before_0140", "before_0141", "after"}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_branding_binding_key")
        result[key] = value
    return result


def _valid_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return (
        all(32 <= ord(character) < 127 for character in value)
        and "\\" not in value
        and ":" not in value
        and not path.is_absolute()
        and bool(path.parts)
        and path.as_posix() == value
        and all(part not in {".", ".."} for part in path.parts)
    )


def load_bindings(
    path: Path, expected_sha256: str, expected_count: int
) -> tuple[dict[str, list[str | None]], dict[str, str | None]]:
    """Require the pinned manifest and canonical, unique, digest-only entries."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular_branding_bindings_file_required")
    with path.open("rb") as source:
        raw = source.read(_MAXIMUM_BYTES + 1)
    if len(raw) > _MAXIMUM_BYTES:
        raise ValueError("branding_bindings_too_large")
    normalized = raw.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized).hexdigest() != expected_sha256:
        raise ValueError("reviewed_branding_bindings_changed")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (
        not isinstance(data, dict)
        or set(data) != {"schema_version", "files"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or not isinstance(data["files"], list)
        or len(data["files"]) != expected_count
    ):
        raise ValueError("invalid_branding_bindings_schema")
    reviewed: dict[str, list[str | None]] = {}
    baseline_0141: dict[str, str | None] = {}
    seen: set[str] = set()
    for row in data["files"]:
        if not isinstance(row, dict) or set(row) != _FIELDS or not _valid_path(row["path"]):
            raise ValueError("invalid_branding_binding_entry")
        name = row["path"]
        if name.casefold() in seen:
            raise ValueError("duplicate_branding_binding_path")
        for key in ("before_0140", "before_0141", "after"):
            value = row[key]
            if value is None and key != "after":
                continue
            if not isinstance(value, str) or _HASH.fullmatch(value) is None:
                raise ValueError("invalid_branding_binding_digest")
        seen.add(name.casefold())
        reviewed[name] = [row["before_0140"], row["after"]]
        baseline_0141[name] = row["before_0141"]
    return reviewed, baseline_0141
