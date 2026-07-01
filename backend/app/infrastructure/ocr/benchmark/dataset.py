"""Versioned JSON benchmark dataset contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    image_path: Path
    expected_fields: dict[str, str]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkDataset:
    name: str
    version: str
    cases: tuple[BenchmarkCase, ...]

    @classmethod
    def load(cls, manifest_path: Path) -> BenchmarkDataset:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        cls._validate_payload(payload)
        base_path = manifest_path.parent.resolve()
        cases = tuple(
            BenchmarkCase(
                case_id=item["id"],
                image_path=(base_path / item["image"]).resolve(),
                expected_fields={str(key): str(value) for key, value in item["expected"].items()},
                tags=tuple(str(tag) for tag in item.get("tags", [])),
            )
            for item in payload["cases"]
        )
        for case in cases:
            if not case.image_path.is_relative_to(base_path):
                raise ValueError(f"Benchmark image escapes dataset directory: {case.case_id}")
            if not case.image_path.is_file():
                raise ValueError(f"Benchmark image does not exist: {case.image_path}")
        return cls(name=payload["name"], version=payload["version"], cases=cases)

    @staticmethod
    def _validate_payload(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Benchmark manifest must be a JSON object")
        if not all(isinstance(payload.get(key), str) for key in ("name", "version")):
            raise ValueError("Benchmark manifest requires string name and version")
        if not isinstance(payload.get("cases"), list) or not payload["cases"]:
            raise ValueError("Benchmark manifest requires at least one case")
        case_ids: set[str] = set()
        for item in payload["cases"]:
            if not isinstance(item, dict) or not all(key in item for key in ("id", "image", "expected")):
                raise ValueError("Every benchmark case requires id, image, and expected")
            if item["id"] in case_ids:
                raise ValueError(f"Duplicate benchmark case id: {item['id']}")
            if not isinstance(item["expected"], dict) or not item["expected"]:
                raise ValueError(f"Benchmark case {item['id']} has no expected fields")
            case_ids.add(item["id"])
