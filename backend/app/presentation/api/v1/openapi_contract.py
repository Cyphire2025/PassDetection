"""Publish the same authentication and error representations used at runtime."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from app.core.config.settings import Settings
from app.presentation.middleware.error_response import HTTP_ERROR_CODES, ApiErrorResponse


def _dashboard_auth(dependant: Dependant) -> bool:
    call = dependant.call
    if getattr(call, "__module__", "") == "app.presentation.dependencies.auth" and getattr(
        call, "__name__", ""
    ) in {"get_authenticated_user", "get_current_user"}:
        return True
    return any(_dashboard_auth(child) for child in dependant.dependencies)


def install_openapi_contract(app: FastAPI, settings: Settings) -> None:
    def schema() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        components = document.setdefault("components", {})
        definitions = components.setdefault("schemas", {})
        error_schema = ApiErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions.update(error_schema.pop("$defs", {}))
        definitions["ApiErrorResponse"] = error_schema
        components.setdefault("securitySchemes", {})["DashboardAccessCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.jwt.access_cookie_name,
            "description": "HttpOnly cookie established by dashboard password/MFA authentication. "
            "Unsafe cookie-authenticated requests require a trusted Origin/Referer when no Bearer header is supplied. "
            "Bearer authentication remains a separate supported alternative.",
        }
        components["securitySchemes"]["DashboardRefreshCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.jwt.refresh_cookie_name,
            "description": "HttpOnly rotating refresh credential established by dashboard sign-in. "
            "Cookie requests require a trusted Origin/Referer when no Bearer header is supplied.",
        }
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.include_in_schema:
                continue
            for method in route.methods:
                operation = document.get("paths", {}).get(route.path_format, {}).get(method.lower())
                if not isinstance(operation, dict):
                    continue
                if route.path_format == "/api/v1/auth/refresh" and method == "POST":
                    # OpenAPI security schemes cannot represent a credential in
                    # a JSON body. The empty alternative is that documented body
                    # credential, not permission to refresh without a token.
                    operation["security"] = [{"DashboardRefreshCookie": []}, {}]
                    operation["x-cookie-csrf"] = (
                        "Trusted Origin or Referer is required for cookies when no Bearer header is supplied"
                    )
                if _dashboard_auth(route.dependant):
                    operation["security"] = [{"HTTPBearer": []}, {"DashboardAccessCookie": []}]
                    if method not in {"GET", "HEAD", "OPTIONS"}:
                        operation["x-cookie-csrf"] = (
                            "Trusted Origin or Referer is required for cookies when no Bearer header is supplied"
                        )
                responses = operation.setdefault("responses", {})
                for code in HTTP_ERROR_CODES:
                    key = str(code)
                    existing = responses.get(key)
                    # Replace FastAPI's generated validation placeholder, while
                    # retaining explicit workflow and health response contracts.
                    generated_validation = key == "422" and "HTTPValidationError" in str(existing)
                    if existing is None or generated_validation:
                        responses[key] = {
                            "description": HTTP_ERROR_CODES[code],
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ApiErrorResponse"}
                                }
                            },
                        }
                for response in responses.values():
                    response.setdefault("headers", {})["X-Request-ID"] = {
                        "description": "Request correlation identifier; never an authentication credential",
                        "schema": {"type": "string"},
                    }
        app.openapi_schema = document
        return document

    # FastAPI explicitly supports replacing this method with a schema factory.
    app.openapi = schema  # type: ignore[method-assign]
