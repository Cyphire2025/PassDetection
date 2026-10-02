# Delete a connection from MCP Devices

Every Devices row provides Delete, including active, disabled, expired and disconnected connections. Manage uses the same Delete connection action. A confirmation explains that the connection disappears from Devices, its MCP access stops, and using it again requires a new request and administrator approval.

The authenticated browser sends `DELETE /api/v1/admin/mcp/connections/{connection_id}`. The existing active-superadmin, recent-MFA and cookie-CSRF guards apply. The server locks and refreshes the exact grant row, sets `revoked_at` if needed and marks `revocation_reason=administrator_removed` in the same transaction as one chained `mcp.connection_removed` audit. Repeated successful deletion is idempotent. The existing Devices query excludes revoked grants with that exact marker before pagination. Grants, credentials, historical workflows and foreign-key references are retained; they do not restore access.

The browser removes the ID from all cached connection pages only after `{deleted:true}`. Failure or MFA cancellation preserves the row. Pending deletion prevents duplicate and competing row actions. The list then refreshes, and an empty later page directs the administrator to the previous page.

The Delete route, HTTP contract and frontend callable are classified as `server_control` under `no_server_control`; they are not added to MCP business tools. The facade fingerprint is reviewed for this addition. The inventory gate retains exactly the 20 unrelated baseline classification gaps, without silently approving them.

Qualification passed: 62 backend deletion/device-access/management-audit tests, an isolated actual PostgreSQL HTTP concurrency test (six duplicate Deletes racing refresh), 163 frontend MCP/proxy unit tests, and 17 browser scenarios across desktop and narrow layouts. Scoped Ruff, ESLint, TypeScript, frontend module budgets, canonical OpenAPI and mobile projection checks passed. The backend budget gate retains the two preexisting failures in untouched `document_distribution_responses.py` (262 lines against 260 and complexity 35 against 34). No coverage-floor claim is made.

Deployment updates backend, frontend and proxy together, retains the old workers and infrastructure, and keeps database revision `0125_mcp_connection_requests`. It does not delete any existing connection automatically.
