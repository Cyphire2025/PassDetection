from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"


def test_backend_declares_only_the_verified_python_311_runtime() -> None:
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert pyproject["project"]["requires-python"] == ">=3.11,<3.12"
    assert (BACKEND / ".python-version").read_text(encoding="utf-8").strip() == "3.11"
    assert re.findall(r"^FROM python:([^ ]+)", dockerfile, flags=re.MULTILINE) == [
        "3.11-slim",
        "3.11-slim",
    ]
    assert 'python-version: "3.11"' in workflow
    assert 'python-version: "3.12"' not in workflow


def test_runtime_direct_dependencies_and_build_tooling_are_exactly_pinned() -> None:
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    requirements_lock = (BACKEND / "requirements.lock").read_text(encoding="utf-8")
    active_requirements = [
        line.split("#", 1)[0].strip()
        for line in requirements.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    assert active_requirements
    assert all("==" in requirement for requirement in active_requirements)
    assert pyproject["build-system"] == {
        "requires": ["setuptools==84.0.0", "wheel==0.48.0"],
        "build-backend": "setuptools.build_meta:__legacy__",
    }
    assert "--generate-hashes" in requirements_lock
    assert "--hash=sha256:" in requirements_lock

    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ARG PIP_VERSION=26.2.1" in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert "pip==26.2.1" in workflow
    assert "ruff==0.16.0" in workflow
    assert "uv==0.12.0" in workflow
    assert "pip-audit==2.10.1" in workflow
