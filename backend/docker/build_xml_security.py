"""Build unchanged CPython pyexpat against one reviewed patched Debian library.

No additional apt repository is configured. Upstream source and both Debian
packages are content-pinned; an unsupported interpreter/architecture fails.
Review/remove this narrow backport when the supported stable base incorporates
the same fixes. Debian 2.9.0-1 includes the XML_ParseBuffer bounds fix.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import sysconfig
import urllib.request
from pathlib import Path

DEBIAN = "https://deb.debian.org/debian/pool/main/e/expat/"
PACKAGES = {
    "amd64": {"libexpat1": "190d7f5e45f070c42a12f708fe417d6636cb45fae71175203168bb5c3695081b",
              "libexpat1-dev": "3300a594215607672236055c109974b6d8e90114f178edd76149e17d60323bb2"},
    "arm64": {"libexpat1": "810a63c52c8ff78f30f04da8c78f133a34c24504caed3f9e673ddda0c878f53d",
              "libexpat1-dev": "12e2fccde319e59994f3ba5682e7051c9d17a9b968f75219fca66b4886a5a608"},
}
SOURCES = {
    "Modules/pyexpat.c": "a71e4173e667bc690a3df2b8b8fe434c64a589fff0160d4aabf8a92149ad2ee5",
    "Modules/clinic/pyexpat.c.h": "85101449af31c3a9749bc596b3b10efd90398c5c3d9e4a587beaa20aadb44b5c",
    "Modules/expat/expat_config.h": "fc918070c65fa23613e4ba5a44b3407e5eb2a503ec42fbfeebee19d9e5eb5649",
}


def download(url: str, checksum: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError("Reviewed XML security build input checksum changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def main() -> None:
    if sys.version_info[:3] != (3, 11, 17):
        raise RuntimeError("Review the pyexpat source pin for the new Python base")
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    if architecture not in PACKAGES:
        raise RuntimeError("This architecture has not been qualified")
    root = Path("/build/xml-security")
    for name, checksum in PACKAGES[architecture].items():
        download(f"{DEBIAN}{name}_2.9.0-1_{architecture}.deb", checksum, root / "packages" / f"{name}.deb")
    subprocess.run(["dpkg", "-i", str(root / "packages/libexpat1.deb"), str(root / "packages/libexpat1-dev.deb")], check=True)
    for name, checksum in SOURCES.items():
        download(f"https://raw.githubusercontent.com/python/cpython/v3.11.17/{name}", checksum, root / name)
    output = root / "patched-python"
    output.mkdir()
    includes = sysconfig.get_path("include")
    command = shlex.split(sysconfig.get_config_var("LDSHARED")) + shlex.split(sysconfig.get_config_var("CFLAGS"))
    command += ["-fPIC", f"-I{includes}", f"-I{includes}/internal", f"-I{root}/Modules/expat",
                str(root / "Modules/pyexpat.c"), "-lexpat", "-o", str(output / ("pyexpat" + sysconfig.get_config_var("EXT_SUFFIX")))]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
