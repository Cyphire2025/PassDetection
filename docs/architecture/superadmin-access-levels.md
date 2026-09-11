# Superadmin access levels

The top bar account menu lets an active Superadmin select Superadmin, Manager,
Staff, or Coordinator within the same sign-in. Selecting a role requires no
password, MFA challenge, or confirmation. Other account types retain their
ordinary account display and cannot call the switching endpoint successfully.
The Coordinator workspace includes the same menu so the user can return to
Superadmin from that layout.

## Identity and scope

The selected access level changes both the interface and server authorization.
The stored user ID, name, account role, and agency remain unchanged. Audit events
continue to identify the real operator. This is a role change for the current
session, not impersonation of another employee.

Manager mode uses the selected agency's manager permissions, including selected
submission deletion. Staff mode uses staff permissions, including WhatsApp
management, with existing ownership and assignment restrictions. Coordinator
mode uses the account's existing coordinator assignments. Switching does not
create assignments or inherit another employee's groups, so a coordinator with
no assignments can have an empty workspace.

For a lower role, the API retains the current selected agency, uses the account's
agency, or infers the agency of the most recently created active group owned by
the account. If there is just one active agency, it can use that agency. When
multiple agencies remain ambiguous, the menu displays the available agencies
and selecting one completes the pending role change.

## Session behavior

`POST /api/v1/auth/access-level` accepts a role and optional agency ID. It always
authenticates the real stored account, which must still be an active Superadmin.
Cookie-authenticated calls retain the existing CSRF checks. The route writes an
`auth.access_level_changed` audit event and returns the effective user response.

A signed, HttpOnly session cookie carries the selected role and agency. It is
bound to the real user, session version, and sign-in deadline. HTTP dependencies
and dashboard WebSocket authorization apply the same selection after validating
the stored identity. Refresh retains the selected role without replacing the
actual role in the access token. Login, logout, and session replacement clear the
selection. Returning to Superadmin clears it without interpreting the old mode
cookie, allowing recovery from an invalid selection.

The browser confirms the selection with `/auth/me`, clears cached protected
queries, and navigates to an allowed workspace. Protected content is unmounted
during the transition. Other tabs reconcile the shared session through browser
events and session refresh. Owner-scoped offline attendance data is retained.

Only the act of switching has no additional MFA requirement. Existing login,
account-security, and sensitive-action MFA requirements remain in effect and
use the actual account role. A lower role cannot bypass those requirements.

## Mutation revalidation and release

Workflows that release the authentication transaction while parsing files later
lock and revalidate the real account, then reapply the selected role. They check
the stored role, tenant, active state, credential state, and session version
before retaining that selection. This covers WhatsApp imports, document
distribution, renaming, bulk approval, and Excel imports.

This feature requires the backend and frontend releases together. It adds no
database migration or environment variable. Worker jobs receive the existing
authorized identifiers and do not depend on the browser's access-level cookie.

Regression coverage includes signed-cookie HTTP authentication and role changes,
refresh and MFA identity preservation, non-Superadmin denial, tenant isolation,
mutation actor revalidation, WebSocket authorization, UI transitions, and
cross-tab session handling. Local database tests use SQLite and do not establish
PostgreSQL row-lock concurrency behavior or production deployment success.

`frontend/scripts/verify-access-level-browser.mjs` exercises the built frontend
against synthetic API responses, covering all four selections, persistence
after refresh, cross-tab changes, and the absence of the selector for ordinary
accounts. Its desktop/mobile screenshots and JSON report are written beneath
`frontend/test-results/access-level-browser/`. This browser check does not sign
in to production or send messages or delete production data.
