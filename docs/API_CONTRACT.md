# Backend API contract

The generated, reviewed reference is [`backend/contracts/api.openapi.json`](../backend/contracts/api.openapi.json). It contains the actual registered `/api/v1` paths, request models, authentication alternatives, response models and file media types. Generate/check it with the qualified Python 3.11 environment:

```powershell
cd backend
.venv311\Scripts\python.exe scripts/export_api_contract.py
# Only after intentionally changing the interface:
.venv311\Scripts\python.exe scripts/export_api_contract.py --write
```

CI fails on unexplained snapshot drift. Review request fields, requiredness, bounds, authentication, success/error codes and content types in the generated diff; generating a snapshot does not itself prove compatibility. Backward-compatible additions stay in `/api/v1`; removing or changing an existing wire contract requires a separately reviewed migration/deprecation plan or a new API version. Never change a generated file without changing and testing its route implementation.

## Dashboard authentication

`POST /api/v1/auth/login` accepts `application/x-www-form-urlencoded`. A successful password/MFA flow establishes HttpOnly session cookies and returns session/user metadata. It does not return bearer tokens in that JSON response. Protected dashboard paths document cookie and Bearer as alternative authentication methods; both are checked against the same persisted dashboard session family. Unsafe cookie requests additionally require a trusted Origin/Referer. See the authentication remediation evidence for refresh concurrency, replay, revocation and the required one-time dashboard sign-in at migration 0109.

`POST /api/v1/auth/refresh` accepts the refresh cookie or a refresh token in its optional JSON body; a supplied body token takes precedence. Missing credentials are rejected. OpenAPI cannot encode a body credential as a security scheme, so the documented empty security alternative refers to the body-token mechanism, not anonymous refresh. Cookie refresh requires the trusted-origin check. A concurrent rotation can return 409 with `Retry-After: 1`; clients must use the bounded retry flow rather than discard the session immediately.

## Errors and correlation

HTTP error responses use `{"error":{"code":"...","message":"..."}}`, with optional bounded `error.details`. Existing explicit `HTTPException.detail` values remain in the legacy `detail` member for compatible clients. Unexpected 500 responses omit the internal exception and mask sensitive details. Framework validation errors omit submitted input. `X-Request-ID` carries a correlation identifier; it is not a credential. Callers must handle a failed network connection without assuming a JSON response exists.

Readiness and diagnostic 503 responses retain their existing `status`, `checks`, version/revision and capability fields, and add the standard error object. File/range responses retain their actual media types/status codes; they are not wrapped in JSON.

Nginx-generated oversized-request and upstream failures have the same error-object shape and no-store/correlation headers. Upstream business responses pass through unchanged. Client timeouts are a transport exception: [Nginx terminates 408 requests before normal error-page processing](https://github.com/nginx/nginx/blob/release-1.28.0/src/http/ngx_http_request.c#L2374). A terminated connection cannot promise a response body. The local Nginx qualification tests this behavior and actual 413/502 failures.

## Pagination and search

Legacy passport, group, manager and notification array endpoints retain array responses. `limit` is 1–200 and `skip` is 0–100000; callers continue with `skip + limit`. Named bulk/export workflows retain their separate authorization and limits. Stable unique tie-breakers prevent equal timestamps from making the order arbitrary; offset pagination is not a snapshot guarantee under concurrent writes.

Global search is 2–100 characters and at most 30 results; existing staff/manager/tenant/lifecycle restrictions are applied to both indexed candidate branches and returned records. `%`, `_` and backslash are literal text, not user-controlled SQL wildcards. PostgreSQL trigram indexes accelerate selective substrings; two-character or highly common queries can still require a scoped scan. `search-plan-evidence.json` records the actual local 100,001-row workload and its measured limits, not a production capacity promise.

## Browser error reports

`POST /api/v1/observability/frontend-errors` accepts at most 2048 bytes of strict metadata, with an allowlisted static route template. It rejects raw messages, stacks, dynamic URLs, query strings and extra fields. Reports are untrusted browser signals. Shared Redis budgets cap admission per IP and globally; duplicates return the original recorded event reference instead of creating a support reference that was never emitted. The client must validate the returned UUID before displaying it. This diagnostic path does not replace externally delivered outage alerts, which remain deferred.
