"""Export/check the complete reviewed backend OpenAPI contract without services."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "contracts/api.openapi.json"


def application_contract() -> dict[str, Any]:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Use the qualified Python 3.11 toolchain to generate contracts")
    # No real credentials or service access are needed to describe routes.
    for key, value in {
        "APP_SECRET_KEY": "contract-generation-only-not-for-deployment",
        "POSTGRES_PASSWORD": "contract-only",
        "S3_ACCESS_KEY_ID": "contract-only",
        "S3_SECRET_ACCESS_KEY": "contract-only",
    }.items():
        os.environ.setdefault(key, value)
    sys.path.insert(0, str(ROOT))
    original = Path.cwd()
    os.chdir(ROOT)
    try:
        from app.core.config.settings import JWTSettings, Settings
        from app.main import create_application

        settings = Settings(
            _env_file=None,
            app_env="development",
            app_name=Settings.model_fields["app_name"].default,
            app_version=Settings.model_fields["app_version"].default,
            jwt=JWTSettings(
                access_cookie_name="access_token",
                refresh_cookie_name="refresh_token",
                _env_file=None,
            ),
        )
        return create_application(settings, initialize_rate_limit_redis=False).openapi()
    finally:
        os.chdir(original)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="Write an explicit contract change for review"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args()
    rendered = (
        json.dumps(application_contract(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    if options.write:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered, encoding="utf-8", newline="\n")
        print("Wrote complete API contract; review request, security and response changes")
    elif not options.output.is_file() or options.output.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            "Backend API contract drifted. Generate with --write and review the complete diff before accepting it."
        )
    else:
        print("Complete backend API contract matches its reviewed snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
