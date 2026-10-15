"""Prove two GCC source-package matches against the actual amd64 runtime.

PBDS is a development-header issue. Its absence from the four reviewed Debian
runtime packages is not a claim about every third-party template instantiation.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import platform
import posixpath
import re
import subprocess
from pathlib import Path

PACKAGES = ("gcc-14-base", "libgcc-s1", "libgomp1", "libstdc++6")
VERSION = "14.2.0-19"
LIBRARY = "/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.33"
LIBRARY_SHA256 = "972bb2a18b71140dab0240f8a1f68ab3fb1d56bcd4c4f824a91b70888faf5a00"
MANIFEST = Path(__file__).with_name("gcc_runtime_manifest.json")
SIZE_MAX = (1 << 64) - 1
BOUNDARIES = ((SIZE_MAX - 8, 32), (SIZE_MAX, 8), (SIZE_MAX, 32),
              (SIZE_MAX, 1024), (SIZE_MAX, 65536), (SIZE_MAX - 1, 16),
              (SIZE_MAX - 1025, 1024), (SIZE_MAX - 1024, 1024),
              (SIZE_MAX - 65536, 65536))
OPERATORS = (("_ZnwmSt11align_val_tRKSt9nothrow_t", "_ZdlPvSt11align_val_t"),
             ("_ZnamSt11align_val_tRKSt9nothrow_t", "_ZdaPvSt11align_val_t"))


def verify_package_contents(manifest: dict, installed: str, filelists: dict[str, str],
                            root: Path = Path("/")) -> int:
    expected = {name: VERSION for name in PACKAGES}
    rows = [line.split("\t") for line in installed.splitlines()]
    if (len(rows) != len(expected) or any(len(row) != 3 for row in rows)
            or {row[0]: row[1] for row in rows} != expected
            or any(row[2] != "install ok installed" for row in rows)):
        raise RuntimeError("GCC runtime package version or installation state changed")
    packages = manifest.get("packages", [])
    if (manifest.get("schema_version") != 1 or len(packages) != len(PACKAGES)
            or {package["name"] for package in packages} != set(PACKAGES)):
        raise RuntimeError("Incomplete official GCC runtime manifest")
    verified = 0
    for package in packages:
        if package["version"] != VERSION:
            raise RuntimeError("Unreviewed GCC manifest version")
        paths = package["paths"]
        actual = {posixpath.normpath(name) for name in filelists[package["name"]].splitlines()}
        if not actual or actual - set(paths):
            raise RuntimeError("GCC package owns unreviewed runtime files")
        for name, entry in paths.items():
            if not name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError("Invalid official package path")
            path = root / name.lstrip("/")
            # Slim images may remove documentation, but executable components
            # and every existing package file must retain the official bytes.
            optional = name.startswith(("/usr/share/doc/", "/usr/share/gdb/", "/usr/share/gcc/python/",
                                        "/usr/share/lintian/"))
            if optional and not path.exists() and not path.is_symlink():
                continue
            kind = entry["type"]
            if kind == "directory":
                valid = path.is_dir() and not path.is_symlink()
            elif kind == "symlink":
                valid = path.is_symlink() and str(path.readlink()).replace("\\", "/") == entry["target"]
            elif kind == "file":
                valid = (path.is_file() and not path.is_symlink()
                         and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"])
            else:
                valid = False
            if not valid:
                raise RuntimeError("GCC official package content changed: " + name)
            verified += 1
    library = root / LIBRARY.lstrip("/")
    if hashlib.sha256(library.read_bytes()).hexdigest() != LIBRARY_SHA256:
        raise RuntimeError("Unreviewed libstdc++ bytes")
    return verified


def reject_development_components(installed: str, root: Path = Path("/")) -> None:
    for line in installed.splitlines():
        name, status = line.split("\t", 1)
        if status != "install ok installed":
            continue
        name = name.split(":", 1)[0]
        if (re.fullmatch(r"(?:gcc|g\+\+)(?:-\d+)?(?:-x86-64-linux-gnu)?", name)
                or re.fullmatch(r"libstdc\+\+-\d+-dev", name)):
            raise RuntimeError("GCC compiler or development headers reintroduced")
    for base in ("usr/include", "usr/local", "usr/bin", "opt", "app"):
        for path in (root / base).rglob("*"):
            if ("pb_ds" in path.parts or path.name == "erase_fn_imps.hpp"
                    or ((path.is_file() or path.is_symlink()) and re.fullmatch(
                        r"(?:(?:x86_64-linux-gnu-)?(?:gcc|g\+\+|c\+\+|cc))(?:-\d+)?", path.name))):
                raise RuntimeError("Affected PBDS header or compiler present: " + str(path))


def aligned_new_boundaries(cpp) -> int:
    handler = cpp._ZSt15get_new_handlerv
    handler.argtypes = []
    handler.restype = ctypes.c_void_p
    if handler() is not None:
        raise RuntimeError("Aligned-new probe requires the normal null new-handler")
    nothrow = ctypes.c_char.in_dll(cpp, "_ZSt7nothrow")
    tag = ctypes.c_void_p(ctypes.addressof(nothrow))
    checked = 0
    for name, delete_name in OPERATORS:
        allocate = getattr(cpp, name)
        allocate.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
        allocate.restype = ctypes.c_void_p
        deallocate = getattr(cpp, delete_name)
        deallocate.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        deallocate.restype = None
        normal = allocate(128, 32, tag)
        if normal is None:
            raise RuntimeError("Aligned-new control allocation failed")
        aligned = normal % 32 == 0
        deallocate(normal, 32)
        if not aligned:
            raise RuntimeError("Aligned-new control was not aligned")
        for size, alignment in BOUNDARIES:
            result = allocate(size, alignment, tag)
            if result is not None:
                deallocate(result, alignment)
                raise RuntimeError("Aligned-new returned an unsafe undersized allocation")
            checked += 1
    return checked


def probe_gcc_runtime() -> dict:
    if (platform.system() != "Linux" or platform.machine() != "x86_64"
            or ctypes.sizeof(ctypes.c_size_t) != 8):
        raise RuntimeError("GCC dispositions support only reviewed Linux amd64 ABI")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    installed = subprocess.check_output([
        "dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n", *PACKAGES,
    ], text=True)
    filelists = {name: subprocess.check_output(["dpkg-query", "-L", name], text=True) for name in PACKAGES}
    verified = verify_package_contents(manifest, installed, filelists)
    inventory = subprocess.check_output(["dpkg-query", "-W", "-f=${binary:Package}\t${Status}\n"], text=True)
    reject_development_components(inventory)
    checked = aligned_new_boundaries(ctypes.CDLL(LIBRARY))
    return {"library_sha256": LIBRARY_SHA256, "version": VERSION,
            "official_package_paths_verified": verified, "aligned_new_boundary_cases": checked,
            "aligned_new_normal_controls": 2, "pbds_development_component": "absent",
            "pbds_scope": "Only the four exact Debian runtime packages; not proof about every third-party template instantiation."}


if __name__ == "__main__":
    print(json.dumps(probe_gcc_runtime()))
