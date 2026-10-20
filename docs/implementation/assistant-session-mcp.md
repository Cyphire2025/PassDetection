# Assistant access through the dashboard session

The website assistant discovers and calls the existing reviewed MCP registry using
the authenticated dashboard account. An external Codex or ChatGPT connection is
not required. The legacy `mcp_connection_id` setting is retained for compatibility
but no longer selects authority for the assistant.

Discovery is observational: it creates no grant or credential. A tool invocation
retains one private authority row per dashboard session in the existing grant
table because operation receipts, artifacts and asynchronous workflows reference
that table. Its reserved first-party identity cannot obtain OAuth credentials,
authenticate at public MCP endpoints, or appear in external device management.
Only short-lived server credentials invoke the existing audited wrappers; they
are removed after the call and never returned to the browser or model.

Each use checks the real dashboard session, account security version, MFA
enrollment, original verified MFA timestamp, AI enable/write settings and current
MCP capabilities, tool and section policy. Logout and session revocation remove
authority, including for delayed work. The existing super-administrator boundary
is preserved. Writes default off and still require explicit user intent and each
tool's validation, confirmation and idempotency workflow. External grants and
global MCP permissions are not modified.

Authority checks and effects acquire their own transaction barriers in the order
AI settings, MCP control, identity, dashboard session, and private grant. The
assistant bridge does not retain a second transaction's settings lock while
waiting for an invocation. HTTP and voice requests share verified dashboard
claims. `/settings/mcp-access` and `/live` report saved effective access, including
paused, disabled, no-tools and sign-in states.

Regression coverage includes no/revoked external connections, permission changes
between discovery and execution, logout/security changes, private-token rejection,
external device isolation, read-only discovery, idempotent writes, voice claims,
settings persistence and browser audio. PostgreSQL-only contention tests are in
`backend/tests/service_integration/test_assistant_mcp_authority_postgresql.py`;
they require the isolated service fixture and must never use production data.
