"""Verify actual driver linkage and optionally exercise SCRAM and verified TLS.

No vulnerability exclusions are granted here. The installed source provenance
and every loaded native client are checked before the connection probe runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

MANIFEST = Path(__file__).with_name("postgresql_client_build.json")
LIBRARY = Path("/opt/postgresql/lib/libpq.so.5")
FORBIDDEN = ("libkrb5", "libk5crypto", "libgssapi", "libsasl", "libldap", "liblber")


def verify_inventory(roots: tuple[Path, ...], library: Path) -> None:
    """Inspect native filenames without loading every shared object into memory."""
    for root in roots:
        for path in root.rglob("*.so*"):
            if not path.is_file():
                continue
            if path.name.startswith(FORBIDDEN):
                raise RuntimeError("An unneeded native authentication library remains")
            if path.name.startswith("libpq") and path.resolve() != library.resolve():
                raise RuntimeError("An unreviewed bundled database library remains")


def verify_linkage(linkage: str, library: Path) -> None:
    if "not found" in linkage or any(name in linkage for name in FORBIDDEN):
        raise RuntimeError("Database client links an unexpected or missing native dependency")
    loaded = re.findall(r"libpq[^\s]*\s+=>\s+(\S+)", linkage)
    if len(loaded) != 1 or Path(loaded[0]).resolve() != library.resolve():
        raise RuntimeError("Python driver did not load the exact reviewed libpq")
    if "libssl.so" not in linkage or "libcrypto.so" not in linkage:
        raise RuntimeError("Database client lost OpenSSL support")


def inspect_client() -> dict[str, object]:
    import psycopg2._psycopg as driver
    from psycopg2.extensions import libpq_version

    manifest = json.loads(MANIFEST.read_text())
    if libpq_version() != manifest["libpq_version"]:
        raise RuntimeError("Loaded libpq version differs from reviewed source")
    verify_inventory((Path("/opt"), Path("/usr/local/lib"), Path("/usr/lib")), LIBRARY)
    linkage = subprocess.check_output(["ldd", str(driver.__file__)], text=True, timeout=15)
    verify_linkage(linkage, LIBRARY)
    return {"libpq_version": libpq_version(), "libpq_sha256": hashlib.sha256(LIBRARY.read_bytes()).hexdigest(),
        "source_sha256": manifest["source"]["sha256"], "openssl_linked": True,
        "unneeded_auth_libraries_absent": True, "bundled_driver_libraries_absent": True}


def database_probe(*, require_tls: bool) -> dict[str, object]:
    import psycopg2

    parameters = {key: os.environ["POSTGRES_" + name] for key, name in (
        ("host", "HOST"), ("dbname", "DB"), ("user", "USER"), ("password", "PASSWORD"))}
    parameters.update(port=os.environ.get("POSTGRES_PORT", "5432"), connect_timeout="10",
        require_auth="scram-sha-256", options="-c statement_timeout=5000 -c lock_timeout=1000")
    if require_tls:
        parameters.update(sslmode="verify-full", sslrootcert=os.environ["PGSSLROOTCERT"], channel_binding="require")
    with psycopg2.connect(**parameters) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE native_client_probe(value text) ON COMMIT DROP")
            cursor.execute("INSERT INTO native_client_probe VALUES (%s)", ("synthetic-round-trip",))
            cursor.execute("SELECT value FROM native_client_probe")
            if cursor.fetchone() != ("synthetic-round-trip",):
                raise RuntimeError("Database client round trip failed")
        tls = connection.info.ssl_in_use
        if require_tls and not tls:
            raise RuntimeError("Database client did not establish verified TLS")
    return {"scram_authentication": True, "database_round_trip": True,
        "tls_in_use": tls, "tls_hostname_and_chain_verified": require_tls}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--require-tls", action="store_true")
    args = parser.parse_args()
    if args.require_tls and not args.database:
        parser.error("--require-tls requires --database")
    result = inspect_client()
    if args.database:
        result.update(database_probe(require_tls=args.require_tls))
    print(json.dumps({"status": "passed", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
