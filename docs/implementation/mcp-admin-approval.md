# MCP administrator approval and access pages

The native Streamable HTTP endpoint remains `/mcp`. Clicking Authenticate now creates a pending connection request and opens the public `/mcp/connect` waiting page. The requesting browser does not need a Global Connects dashboard account or login session.

The waiting page says: **Waiting for administrator approval. Your access request is awaiting administrator approval. You can use Global Connects once an administrator approves this connection.** It shows a comparison code and tells the requester to keep the tab open. A separate signed-in superadmin compares that code and approves or rejects the request from `/admin/mcp/requests`.

## Administration

The top navigation has four separate routes:

- `/admin/mcp`: Devices, with independent Enable and Disable actions for each approved named connection.
- `/admin/mcp/requests`: pending requests and recent decisions; approval selects a name, platform and permitted scopes.
- `/admin/mcp/settings`: global pause/resume, section read permissions using settings rows and switches, and access monitoring.
- `/admin/mcp/setup`: authorization status, the MCP URL and direct native app instructions.

The old Advanced section, duplicate Connections view and Try a read in Codex section are removed. Existing read permission revision conflict handling and recent MFA confirmation remain enforced. Platform and device names are labels for OAuth connections; the service does not attest physical hardware. A client that shares one grant between machines cannot be separately controlled by hardware.

## Request authority

A validated authorization GET stores the original client, callback, resource, state, PKCE challenge and requested capabilities. A ten-minute pending request uses a unique high-entropy browser secret in scoped Secure HttpOnly SameSite=Lax cookies; only its keyed digest is stored. The public URL contains a request UUID, not the secret or OAuth state. Public status requires the cookie and matching X-MCP-Request header; mutations also require the configured frontend origin. The human comparison code is not an access credential.

Approval records only the decision, approving account, security version, MFA time and approved scopes. It creates no grant or authorization code. Finalization by the original browser rechecks current identity and deployment authority under consistent database locks, creates exactly one grant and short-lived authorization code, and returns the original native callback with code, state and issuer. Rejection returns access_denied without credentials. Account disablement, security-version changes, global pause, expired requests and reduced deployment capabilities fail closed. Terminal rejected and finalized statuses remain stable after the request deadline.

Database quotas serialize request admission across processes. Request-source attribution follows the existing trusted-proxy policy; arbitrary forwarding headers from untrusted clients do not alter that attribution. The ten-minute server lifetime does not guarantee how long a native client's sign-in window will wait.

## Release boundary

Schema `0125_mcp_connection_requests` adds the request table to the existing `0124_mcp_device_access` schema. The separate exact 0124-to-0125 helper preserves all four existing authority tables, including enabled and platform decisions. It strictly validates the request schema, constraints, indexes and owner role. The upgrade and idempotent pre-activation path require an empty request table; the runtime schema-only probe allows legitimate pending requests. Automatic downgrade is refused.

The new release operator uses retained SHA-pinned primitive libraries in an explicit new context. It takes a fresh current-state baseline, retains all previously present containers and images, fences writers and drains queues, creates and verifies a full database backup, applies the exact migration through an owner-role helper, and verifies the runtime role can SELECT, INSERT and UPDATE the new table before activation. Recovery selects a source-compatible prior application before migration or the schema-compatible candidate with MCP disabled after migration. Unknown schema or a running migration helper leaves writers fenced for inspection. There is no cleanup, automatic retry or new missing-resource exception.

The independent live verifier uses read-only database queries and safe public probes. Valid authorization GET requests are deliberately excluded because they now create pending requests. The full approval-to-token and simultaneous decision/finalization flows are qualified against disposable local PostgreSQL databases.

## Qualification before deployment

- Backend OAuth, device, audit and OpenAPI suite: 117 passing tests, with separate focused cookie and terminal-status regressions.
- Actual PostgreSQL concurrency/quota flow: passing; simultaneous approve/reject and finalize operations produce only one decision and one grant/code.
- New and historical migration helper unit suite: 104 passing tests. Four actual PostgreSQL helper CLI scenarios pass.
- Frontend MCP/proxy unit suite: 151 passing tests across fourteen suites. Production build, TypeScript, scoped ESLint and module budgets pass.
- Eleven isolated browser scenarios pass, including layouts at 1440, 650 and 390 pixels, independent device controls, approve/reject, MFA cancellation and pause/resume, anonymous approval callbacks, and read-access conflicts. Browser fixtures use loopback API destinations and never production records.
- Read-only production preflight confirms the existing migrator default privilege policy grants the runtime role each of SELECT, INSERT and UPDATE on future tables. The operator independently checks each permission on the actual new table before activation.

Repository-wide backend quality ratchets still report the two existing document distribution budget failures (262/260 lines and 35/34 complexity); the changed MCP modules stay within their applicable budgets. Unchanged business surface qualification gaps are not represented as completed by this release.
