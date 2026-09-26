"""Build unchanged CPython pyexpat against one reviewed patched Debian library.

No additional apt repository is configured. Upstream source and both Debian
packages are content-pinned; an unsupported interpreter/architecture fails.
Review/remove this narrow backport when the supported stable base incorporates
the same fixes. Debian 2.8.4-2 includes Expat 2.8.5 UTF-16 security patches.
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
    "amd64": {"libexpat1": "b7dc32b95693aab0a078d0e3802f0b43b3fe7d57ef5e578e100d09fa8b46df87",
              "libexpat1-dev": "9822db6a65781e4f8212d53c560874c1759f7d4b26958435ad4eab7927baec50"},
    "arm64": {"libexpat1": "8c83560c38bcf4998c6c80b68a3e6601c06630e8c864f59b2c246d44a5d41013",
              "libexpat1-dev": "24b632bdf4a06c36c8ce6ccd0f75aa5a2ea6ba3ee1eb7db766daae1168671dd3"},
}
SOURCES = {
    "Modules/pyexpat.c": "3804299cf1b69dcb66d06631c98a2ce40e745ae3194a12e8880990a896ad75d4",
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
    if sys.version_info[:3] != (3, 11, 16):
        raise RuntimeError("Review the pyexpat source pin for the new Python base")
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    if architecture not in PACKAGES:
        raise RuntimeError("This architecture has not been qualified")
    root = Path("/build/xml-security")
    for name, checksum in PACKAGES[architecture].items():
        download(f"{DEBIAN}{name}_2.8.4-2_{architecture}.deb", checksum, root / "packages" / f"{name}.deb")
    subprocess.run(["dpkg", "-i", str(root / "packages/libexpat1.deb"), str(root / "packages/libexpat1-dev.deb")], check=True)
    for name, checksum in SOURCES.items():
        download(f"https://raw.githubusercontent.com/python/cpython/v3.11.16/{name}", checksum, root / name)
    output = root / "patched-python"
    output.mkdir()
    includes = sysconfig.get_path("include")
    command = shlex.split(sysconfig.get_config_var("LDSHARED")) + shlex.split(sysconfig.get_config_var("CFLAGS"))
    command += ["-fPIC", f"-I{includes}", f"-I{includes}/internal", f"-I{root}/Modules/expat",
                str(root / "Modules/pyexpat.c"), "-lexpat", "-o", str(output / ("pyexpat" + sysconfig.get_config_var("EXT_SUFFIX")))]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
