"""Build supported libpq and the locked psycopg driver without unused auth stacks.

Upstream source archives are SHA256-pinned. Only libpq, build headers and
pg_config are installed; no PostgreSQL server or modified upstream code is built.
The final image copies libpq plus provenance and discards the build toolchain.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path("/build/postgresql-client")
MANIFEST = Path(__file__).with_name("postgresql_client_build.json")
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def stage_runtime_libraries(source: Path, destination: Path) -> None:
    """Preserve libpq aliases inside one minimal directory for Docker COPY."""
    destination.mkdir(parents=True)
    for library in source.glob("libpq.so*"):
        if library.resolve().parent != source.resolve():
            raise RuntimeError("Native library alias escapes the reviewed directory")
        shutil.copy2(library, destination / library.name, follow_symlinks=False)
    if not (destination / "libpq.so.5").is_file():
        raise RuntimeError("Reviewed runtime library was not staged")


def download(entry: dict[str, str], destination: Path) -> None:
    """Stream an admitted source with a 64 MiB cap and exact content checksum."""
    digest, total = hashlib.sha256(), 0
    with urllib.request.urlopen(entry["url"], timeout=60) as response, destination.open("xb") as target:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise RuntimeError("Native client source exceeds the reviewed size budget")
            digest.update(chunk)
            target.write(chunk)
    if digest.hexdigest() != entry["sha256"]:
        raise RuntimeError("Reviewed native client source checksum changed")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    ROOT.mkdir(parents=True)
    archive = ROOT / "postgresql.tar.bz2"
    download(manifest["source"], archive)
    with tarfile.open(archive) as source:
        source.extractall(ROOT, filter="data")
    source_root = ROOT / ("postgresql-" + manifest["version"])
    subprocess.run(["./configure", *manifest["configure"]], cwd=source_root, check=True, timeout=180)
    # Upstream libpq targets build their common/port dependencies. Generated
    # headers are explicit so the same recipe works for both supported arches.
    for directory, target in (("src/backend", "generated-headers"),
                              ("src/include", "install"),
                              ("src/interfaces/libpq", "install"),
                              ("src/bin/pg_config", "install")):
        subprocess.run(["make", "-j2", "-C", directory, target], cwd=source_root, check=True, timeout=600)
    driver = ROOT / "psycopg2-binary-2.9.9.tar.gz"
    download(manifest["psycopg2_source"], driver)
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-cache-dir", "--no-deps",
        "--no-build-isolation", "--wheel-dir=/pq-wheels", str(driver)], check=True, timeout=180)
    stage_runtime_libraries(Path("/opt/postgresql/lib"), Path("/pq-runtime"))


if __name__ == "__main__":
    main()
