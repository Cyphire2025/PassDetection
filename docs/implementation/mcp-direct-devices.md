# Native remote MCP and device access

Implemented on branch `codex/mcp-direct-devices`, based on
`db987053166b5f30bb413e27bf9f53e4885fd0a4`. This checkpoint records local
implementation and qualification. It does not claim deployment or successful
sign-in in a real installed ChatGPT or Codex client.

## Connection flow

Use the app's native custom MCP form:

| Field | Value |
| --- | --- |
| Name | Global Connects |
| Type | Streamable HTTP |
| URL | `https://tech.gctravels.com/mcp` on the production host; use the dashboard's displayed URL on other deployments |
| Bearer token environment variable | Leave empty |
| Headers and headers from environment variables | Leave empty |

The client discovers OAuth and opens Global Connects in the browser. The
administrator signs in, completes the existing identity check when required,
names the connection, selects Windows, macOS or Other, and approves its
permissions. This flow requires no local Global Connects connector, command,
executable or STDIO bridge. Saving the URL alone grants no access.

The remote server supports OpenAI's published ChatGPT and Codex client metadata
documents. Authorization and code exchange fetch only those two exact HTTPS
destinations, with redirects and environment proxies disabled, a five-second
deadline, a 16 KiB response cap, and a positive cache of at most five minutes.
Failed refresh never falls back to stale metadata. ChatGPT callbacks are exact;
Codex supports a valid variable port on literal `127.0.0.1` at `/callback`.
Code exchange binds the exact original callback, resource and PKCE verifier.
Native browser callbacks require the matching issuer and state.

## Separate access controls

The primary MCP page displays the URL with Copy, the direct setup guide, and a
separate Devices section before read-section settings. Each saved authorization
has its own platform label, status, last-used time, expiry, and Enable or Disable
button. Existing connections remain listed even when they predate platform
labels. Permanent Disconnect remains in Advanced.

Disabling preserves the grant, permissions, codes, tokens, artifacts and history.
The server checks the enabled flag on token/code exchange, refresh, MCP calls and
protected operations. A disabled connection cannot consume an authorization code
or rotate a refresh token. Other connections retain their own access. Enabling
restores the server permission while the grant and account remain valid; a
client that discarded its credentials after denial may need to sign in again.
Expired or revoked grants require a fresh authorization. Existing global pause,
read-section authority, recent MFA, CSRF and superadmin controls still apply.
Already-running work is not retroactively cancelled by this switch.

Names and platforms are administrator-supplied labels for authorizations. The
MCP protocol does not prove a physical device identity. ChatGPT may share one
account connection across several computers, and copied credentials represent
the same entry. A separate consent creates a separate controllable entry. The
UI states this limitation instead of claiming hardware detection or enforcement.

## Schema and retained state

`0124_mcp_device_access` is additive over `0123_mcp_read_sections`. It adds a
non-null enabled flag with true as the default and an optional constrained
platform. It preserves existing global state, grants, tokens, capabilities,
read sections, revisions, identity and business rows. Destructive downgrade is
refused. The release manifest, Compose defaults, example environment and
migration topology agree on revision 0124.

The separate source release contract is `mcp_direct_devices_v1`. Historical
deployment executors reject it before backup or mutation; their authority is
not expanded by this source change. A qualified live rollout for the observed
source schema and installed protected dispatcher is still required. No live
configuration, grants, database, containers, DNS or local Codex setup was changed
as part of this implementation.

## Local evidence

- 198 combined backend cases passed: trusted client policy, native OAuth,
  device access, existing authorization, HTTP boundaries, management audits
  and operations. The native cases exercise the MCP HTTP endpoint; published
  metadata network I/O is substituted in those deterministic tests. A separate
  live metadata fetch validated both current OpenAI documents.
- 117 focused frontend unit cases passed; the final static guide simplification
  was followed by another 28 home cases and affected-file ESLint.
- 13 isolated Chromium journeys passed, including direct consent, independent
  Windows and Mac switches at 1440 and 390 pixels, MFA cancellation, existing
  access editing, revocation and read-only permissions.
- Two qualification cases passed against an actual disposable PostgreSQL 16.15
  loopback cluster, with global access both enabled and disabled. They verify
  populated 0123-to-0124 retention, constraints, concurrent pause/refresh,
  unconsumed refresh credentials while paused, independent grant access,
  successful refresh after reenable, and refusal of destructive downgrade.
- 48 release contract and manifest cases passed. Migration topology and source
  defaults passed. Scoped Ruff, mypy, ESLint, full frontend TypeScript, 40 frontend
  module budgets, and the Next.js production build passed.
- Canonical OpenAPI was regenerated and checked. The mobile OpenAPI check passes
  without changes to mobile source.

These checks do not claim that every repository gate passes. The unchanged
`document_distribution_responses.py` exceeds its preexisting line and complexity
budgets (262/260 lines, complexity 35/34). The MCP inventory retains 20 preexisting
gaps; the [inventory checkpoint](mcp-direct-devices-inventory-checkpoint.md)
records exact equality with the baseline after the six scoped ledger reviews.
There is no new device-access inventory drift.

Browser screenshot evidence uses isolated synthetic authorizations, not live
device records. A real native-client sign-in against the deployed revision
remains an acceptance step after rollout.
