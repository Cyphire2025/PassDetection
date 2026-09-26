"""Backport CPython's exact CVE-2026-82049 fix to the pinned 3.11.16 source.

Upstream: python/cpython b8f23e307097552eaea2604383a12ab280520d0d.
This deliberately changes one operation, not the interpreter or filter policy.
The original whole-file hash and replacement count make base-image drift fatal.
"""
import hashlib
import sys
import tarfile
from pathlib import Path

ORIGINAL_SHA256 = "9e0fd86283caaaf15a884e5f36a5c319a21b74cfc8ae15f853d783d81a2be2e6"
OLD = b"os.link(tarinfo._link_target, targetpath)"
NEW = b"os.link(os.path.realpath(tarinfo._link_target), targetpath)"


def backport(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != ORIGINAL_SHA256 or source.count(OLD) != 1:
        raise ValueError("The pinned tarfile source changed; review upstream before rebuilding")
    return source.replace(OLD, NEW)


if __name__ == "__main__":
    if sys.version_info[:3] != (3, 11, 16):
        raise RuntimeError("This backport was qualified only for Python 3.11.16")
    path = Path(tarfile.__file__)
    path.write_bytes(backport(path.read_bytes()))
    print("CVE-2026-82049 backported tarfile SHA256:", hashlib.sha256(path.read_bytes()).hexdigest())
