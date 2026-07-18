from __future__ import annotations

import ast
from pathlib import Path

_RAW_PII_LOG_FIELDS = {
    "client_name",
    "date_of_birth",
    "email",
    "group_name",
    "mobile",
    "name",
    "passport_number",
    "phone",
    "recipient_name",
    "surname",
}


def test_application_logs_do_not_use_raw_pii_fields() -> None:
    app_root = Path(__file__).resolve().parents[3] / "app"
    violations: list[str] = []

    for source_path in app_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id != "logger":
                continue

            unsafe_fields = sorted(
                keyword.arg
                for keyword in node.keywords
                if keyword.arg in _RAW_PII_LOG_FIELDS
            )
            if unsafe_fields:
                relative_path = source_path.relative_to(app_root.parent)
                violations.append(
                    f"{relative_path}:{node.lineno}: {', '.join(unsafe_fields)}"
                )

    assert not violations, (
        "Raw PII must not be attached to application log records:\n"
        + "\n".join(violations)
    )


def test_application_logs_do_not_serialize_exception_values_or_tracebacks() -> None:
    app_root = Path(__file__).resolve().parents[3] / "app"
    violations: list[str] = []

    for source_path in app_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id != "logger":
                continue

            relative_path = source_path.relative_to(app_root.parent)
            if node.func.attr == "exception":
                violations.append(
                    f"{relative_path}:{node.lineno}: logger.exception"
                )
            for keyword in node.keywords:
                if keyword.arg == "exc_info":
                    violations.append(
                        f"{relative_path}:{node.lineno}: exc_info"
                    )
                if (
                    isinstance(keyword.value, ast.Call)
                    and isinstance(keyword.value.func, ast.Name)
                    and keyword.value.func.id == "str"
                    and keyword.value.args
                    and isinstance(keyword.value.args[0], ast.Name)
                    and keyword.value.args[0].id in {"exc", "error"}
                ):
                    violations.append(
                        f"{relative_path}:{node.lineno}: str(exception)"
                    )

    assert not violations, (
        "Exception messages and tracebacks can contain traveller data; log only "
        "bounded error types/codes:\n" + "\n".join(violations)
    )
