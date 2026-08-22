"""Export or verify the canonical `/api/v1/mobile` OpenAPI contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "mobile" / "contracts" / "mobile-api.openapi.json"
MOBILE_PATH_PREFIX = "/api/v1/mobile"
SCHEMA_REF_PREFIX = "#/components/schemas/"
CANONICAL_PYTHON_VERSION = (3, 11)


def _schema_references(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith(SCHEMA_REF_PREFIX):
            yield reference.removeprefix(SCHEMA_REF_PREFIX)
        for child in value.values():
            yield from _schema_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_references(child)


def mobile_contract(openapi: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        path: value
        for path, value in openapi.get("paths", {}).items()
        if path == MOBILE_PATH_PREFIX or path.startswith(f"{MOBILE_PATH_PREFIX}/")
    }
    schemas = openapi.get("components", {}).get("schemas", {})
    required_schemas = set(_schema_references(paths))
    pending = list(required_schemas)
    while pending:
        name = pending.pop()
        schema = schemas.get(name)
        if schema is None:
            raise ValueError(f"Mobile OpenAPI path references missing schema {name!r}.")
        for referenced in _schema_references(schema):
            if referenced not in required_schemas:
                required_schemas.add(referenced)
                pending.append(referenced)

    components: dict[str, Any] = {
        "schemas": {name: schemas[name] for name in sorted(required_schemas)}
    }
    security_schemes = openapi.get("components", {}).get("securitySchemes", {})
    if security_schemes:
        components["securitySchemes"] = security_schemes
    return {
        "openapi": openapi.get("openapi"),
        "info": {
            "title": openapi.get("info", {}).get("title"),
            "version": openapi.get("info", {}).get("version"),
        },
        "paths": paths,
        "components": components,
    }


def canonical_json(contract: Mapping[str, Any]) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextmanager
def _backend_working_directory() -> Iterator[None]:
    """Make settings-file discovery independent of the caller's shell directory."""

    original = Path.cwd()
    os.chdir(BACKEND_ROOT)
    try:
        yield
    finally:
        os.chdir(original)


def application_contract() -> dict[str, Any]:
    if sys.version_info[:2] != CANONICAL_PYTHON_VERSION:
        expected = ".".join(str(part) for part in CANONICAL_PYTHON_VERSION)
        actual = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise RuntimeError(
            "Mobile OpenAPI generation must use the repository's canonical "
            f"Python {expected} runtime; received Python {actual}."
        )
    # Import lazily so pure contract-selection tests never construct runtime
    # settings, middleware clients, or an application object.
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    # Pydantic resolves the configured `.env` relative to the process working
    # directory. Pin it to `backend/` so a developer invoking this script from
    # the repository root cannot accidentally load the private root `.env` and
    # produce a different API title than CI.
    with _backend_working_directory():
        from app.main import create_application

        return mobile_contract(create_application(initialize_rate_limit_redis=False).openapi())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace the reviewed snapshot")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rendered = canonical_json(application_contract())
    output = args.output.resolve()
    if args.write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        try:
            display_path = output.relative_to(REPOSITORY_ROOT)
        except ValueError:
            display_path = output
        print(f"Wrote mobile OpenAPI contract: {display_path}")
        return

    if not output.is_file():
        raise SystemExit(
            "Mobile OpenAPI snapshot is missing. Review the API change, then run "
            "`python scripts/export_mobile_openapi_contract.py --write`."
        )
    reviewed = output.read_text(encoding="utf-8")
    if reviewed != rendered:
        raise SystemExit(
            "Mobile OpenAPI contract drifted. Regenerate the snapshot, review the diff, "
            "and update mobile validators in the same change."
        )
    print("Mobile OpenAPI contract matches the reviewed snapshot.")


if __name__ == "__main__":
    main()
