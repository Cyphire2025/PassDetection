"""Prepare isolated PostgreSQL 16 clients without changing candidate libraries."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

try:
    from .qualify_postgresql_client import OWNER_LABEL, QualificationError, run
except ImportError:
    from qualify_postgresql_client import OWNER_LABEL, QualificationError, run

# Official multi-platform manifest, verified with buildx imagetools inspect.
POSTGRES_IMAGE = "postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4"
MOUNT = "/qa-pg16"
EXTRACT = r"""
set -eu
umask 022
mkdir /out/lib /out/client /out/bin
for client in pg_dump pg_restore; do
  binary="/usr/lib/postgresql/16/bin/$client"
  test -f "$binary"
  cp "$binary" "/out/client/$client"
  ldd "$binary" > "/out/$client.dependencies"
  if grep -q 'not found' "/out/$client.dependencies"; then exit 41; fi
done
awk '/=> \// {print $3} /^[[:space:]]*\// {print $1}' /out/*.dependencies | sort -u > /out/dependencies
while IFS= read -r library; do
  case "$library" in /lib/*|/lib64/*|/usr/lib/*) ;; *) exit 42 ;; esac
  target="/out/lib/$(basename "$library")"
  if test -f "$target"; then cmp "$library" "$target"; else cp -L "$library" "$target"; fi
  case "$library" in */ld-linux-*.so.*) cp -L "$library" /out/lib/ld.so ;; esac
done < /out/dependencies
test -f /out/lib/ld.so
chmod 755 /out /out/lib /out/client /out/bin /out/lib/ld.so /out/client/*
rm /out/*.dependencies /out/dependencies
"""


def extract_clients(name: str, owner: str, directory: Path) -> dict[str, Any]:
    if os.name != "posix":
        raise QualificationError("Private PostgreSQL client extraction requires the local Linux Docker host")
    directory.mkdir(mode=0o755)
    run(["docker", "create", "--name", name, "--network", "none", "--read-only",
         "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=2",
         "--label", f"{OWNER_LABEL}={owner}", "--memory", "128m", "--memory-swap", "128m",
         "--cpus", "0.5", "--pids-limit", "32", "--cap-drop", "ALL",
         "--security-opt", "no-new-privileges:true", "--user", f"{os.getuid()}:{os.getgid()}",
         "--mount", f"type=bind,source={directory},target=/out",
         "--entrypoint", "sh", POSTGRES_IMAGE, "-ec", EXTRACT])
    run(["docker", "start", "--attach", name], timeout=90)
    for client in ("pg_dump", "pg_restore"):
        path = directory / "bin" / client
        path.write_text(f'#!/bin/sh\nexec {MOUNT}/lib/ld.so --library-path {MOUNT}/lib '
                        f'{MOUNT}/client/{client} "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return validate_client_tree(directory)


def validate_client_tree(directory: Path) -> dict[str, Any]:
    """Bound the private copy and reject aliases, escaped paths and special files."""
    entries: dict[str, str] = {}
    total = 0
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            path.chmod(0o755)
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise QualificationError("Private client fixture contains an unreviewed file type or alias")
        relative = path.relative_to(directory).as_posix()
        if re.fullmatch(r"(?:lib/[A-Za-z0-9_.+-]+|(?:bin|client)/pg_(?:dump|restore))", relative) is None:
            raise QualificationError("Private client fixture contains an unexpected path")
        total += info.st_size
        if total > 128 * 1024 * 1024 or len(entries) >= 128:
            raise QualificationError("Private client fixture exceeds its bounded size")
        path.chmod(0o755 if relative.startswith(("bin/", "client/")) or relative == "lib/ld.so" else 0o644)
        with path.open("rb") as stream:
            entries[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    if not {"lib/ld.so", "bin/pg_dump", "bin/pg_restore", "client/pg_dump", "client/pg_restore"} <= entries.keys():
        raise QualificationError("Private PostgreSQL client closure is incomplete")
    return {"image": POSTGRES_IMAGE, "files": entries, "bytes": total}
