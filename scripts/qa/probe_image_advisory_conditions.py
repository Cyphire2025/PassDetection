"""Inspect real runtime bytes and process conditions; no scanner suppression.

The ELF reader handles the supported little-endian ELF64 images only and fails
closed on a different ELF class. It checks imported dynamic symbols across all
installed application, Python and OS native objects, rather than only the CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path

from gcc_runtime_policy import probe_gcc_runtime
from native_allocator_policy import reviewed_allocator_source

FORBIDDEN_SYMBOLS = {"strfmon", "strfmon_l", "ns_printrr", "ns_printrrf", "fp_nquery"}


def imported_symbols(data: bytes) -> set[str]:
    if data[:4] != b"\x7fELF":
        return set()
    if data[4:6] != b"\x02\x01":
        raise ValueError("Unqualified ELF architecture/class")
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_size, section_count = struct.unpack_from("<HH", data, 58)
    if not section_offset or not section_count:
        raise ValueError("Native object has no inspectable section table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, section_offset + index * section_size)
                for index in range(section_count)]
    symbols = set()
    for section in sections:
        if section[1] != 11:  # SHT_DYNSYM
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], section[9]):
            name, _info, _other, index, _value, _size = struct.unpack_from("<IBBHQQ", data, offset)
            if index == 0 and name:
                symbols.add(names[name:names.index(b"\0", name)].decode())
    return symbols


def main() -> None:
    gcc_conditions = probe_gcc_runtime()
    absent = ["/usr/bin/infocmp", "/usr/bin/mount", "/usr/bin/umount", "/usr/bin/nsenter", "/usr/bin/tiffcrop",
              "/usr/bin/getfacl", "/usr/bin/setfacl", "/usr/bin/chacl"]
    for filename in absent:
        if Path(filename).exists():
            raise RuntimeError(f"Affected unused executable is installed: {filename}")
    for module in ("Pod::Text", "Archive::Tar"):
        result = subprocess.run(["perl", "-M" + module, "-e", "1"], capture_output=True, check=False)
        missing_target = ("Can't locate " + module.replace("::", "/") + ".pm in @INC").encode()
        if result.returncode == 0 or missing_target not in result.stderr:
            raise RuntimeError("Affected Perl module presence could not be excluded")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if os.getuid() != 1001 or int(status["CapEff"].strip(), 16) or int(status["CapBnd"].strip(), 16) or status["NoNewPrivs"].strip() != "1":
        raise RuntimeError("Privileged-call mitigation requires UID1001, empty effective/bounding capabilities, and NoNewPrivs")
    native = []
    forbidden_imports = []
    python_mentions = []
    reviewed_native_callers = []
    seen = set()
    token = re.compile(r"\b(?:strfmon|strfmon_l|ns_printrr|ns_printrrf|fp_nquery)\b")
    ffi = re.compile(r"\b(?:ctypes|cffi|dlopen|dlsym|CDLL|PyDLL|LoadLibrary)\b")
    privileged = re.compile(r"\b(?:acl_get_file|acl_set_file|acl_extended_file|acl_delete_def_file|setfacl|getfacl|chacl|nsenter|infocmp)\b")
    for root in (Path("/usr/bin"), Path("/usr/sbin"), Path("/usr/lib"), Path("/usr/local"), Path("/opt"), Path("/app")):
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.suffix == ".py":
                source_bytes = path.read_bytes()
                source = source_bytes.decode(errors="replace")
                allocator = reviewed_allocator_source(str(path), source_bytes)
                if allocator:
                    reviewed_native_callers.append(allocator)
                if token.search(source) or (str(path).startswith("/app/") and (
                        privileged.search(source) or (ffi.search(source) and allocator is None))):
                    python_mentions.append(str(path))
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
                stream.seek(0)
                content = stream.read()
            imports = imported_symbols(content)
            hit = sorted(imports & FORBIDDEN_SYMBOLS)
            if hit:
                forbidden_imports.append({"file": str(path), "symbols": hit})
            native.append({"file": str(path), "sha256": hashlib.sha256(content).hexdigest()})
    if forbidden_imports or python_mentions:
        raise RuntimeError(json.dumps({"native_callers": forbidden_imports, "python_mentions": python_mentions}))
    library = next(Path("/usr/lib").glob("*-linux-gnu/libz.so.1.3.1"))
    zlib_sha = hashlib.sha256(library.read_bytes()).hexdigest()
    # This qualified amd64 binary is byte-identical to the official Debian .deb.
    # Its official-source .dsc and all five upstream gz source comparisons are
    # retained in zlib-source-evidence.json, including the introducing commit.
    if zlib_sha != "85590dd58edf5445e18bc7193e5ebc01ac5841f1ae187e97705a662e90c6421e":
        raise RuntimeError("zlib binary changed; repeat the source/binary affected-range review")
    print(json.dumps({"result": "passed", "uid": os.getuid(), "capabilities": "none",
        "no_new_privileges": True, "removed_executables": absent, "absent_perl_modules": ["Pod::Text", "Archive::Tar"],
        "inspected_native_objects": len(native), "native_inventory_sha256": hashlib.sha256(json.dumps(native, sort_keys=True).encode()).hexdigest(),
        "forbidden_symbol_imports": [], "python_symbol_references": [], "zlib_binary_sha256": zlib_sha,
        "reviewed_native_callers": reviewed_native_callers,
        "gcc_runtime_conditions": gcc_conditions,
        "native_inventory": native}))


if __name__ == "__main__":
    main()
