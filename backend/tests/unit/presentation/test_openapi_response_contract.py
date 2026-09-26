from app.main import create_application


def test_auth_validation_file_and_cookie_contracts_match_runtime(test_settings):
    app = create_application(test_settings, initialize_rate_limit_redis=False)
    schema = app.openapi()
    paths = schema["paths"]
    login = paths["/api/v1/auth/login"]["post"]
    assert set(login["requestBody"]["content"]) == {"application/x-www-form-urlencoded"}
    assert "HttpOnly cookies" in login["description"]
    assert "JSON body" in login["description"]
    assert login["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ApiErrorResponse")
    cookie = schema["components"]["securitySchemes"]["DashboardAccessCookie"]
    assert cookie["in"] == "cookie" and cookie["name"] == test_settings.jwt.access_cookie_name
    assert paths["/api/v1/auth/me"]["get"]["security"] == [
        {"HTTPBearer": []}, {"DashboardAccessCookie": []}]
    refresh = paths["/api/v1/auth/refresh"]["post"]
    refresh_cookie = schema["components"]["securitySchemes"]["DashboardRefreshCookie"]
    assert refresh_cookie["in"] == "cookie"
    assert refresh_cookie["name"] == test_settings.jwt.refresh_cookie_name
    assert refresh["security"] == [{"DashboardRefreshCookie": []}, {}]
    assert refresh["requestBody"].get("required", False) is False
    assert "missing credentials return 401" in refresh["description"]
    assert "takes precedence over the cookie" in refresh["description"]
    assert "x-cookie-csrf" in refresh
    for path, media in (("/api/v1/passports/groups/{group_id}/export.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                        ("/api/v1/passports/{submission_id}/images/{image_type}", "image/*"),
                        ("/api/v1/audit-logs/export.csv", "text/csv")):
        content = paths[path]["get"]["responses"]["200"]["content"]
        assert "application/json" not in content
        assert content[media]["schema"] == {"type": "string", "format": "binary"}
    original = paths["/api/v1/passports/{submission_id}/images/{image_type}/original"]["get"]
    assert "206" in original["responses"]
    library = paths["/api/v1/passports/{submission_id}/images/{image_type}/library/{item_id}/image"]["get"]
    assert "206" not in library["responses"]
    assert app.openapi() is schema
