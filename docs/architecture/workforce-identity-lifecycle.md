# Workforce identity lifecycle

This document defines the source-level credential boundary for dashboard staff,
coordinators, and Group Companion Client Managers. Deployment-specific mail,
secret-manager, and app-link configuration sit outside this boundary.

## Security invariants

- An administrator never chooses or receives a user's usable password.
- New and reset accounts receive a random unusable placeholder plus a
  high-entropy, expiring, single-use activation credential.
- Activation and recovery credentials are stored only as purpose-separated
  HMACs. A database partial unique index permits at most one live credential
  per user and purpose. Issuing a replacement invalidates the earlier link.
- Raw activation credentials are returned only in the creation/reset response,
  with `Cache-Control: private, no-store`; they are never written to audit logs.
- Password changes, password recovery, administrative reset, account status
  changes, factor reset, and factor regeneration advance an authoritative
  session generation and revoke refresh credentials. Staff-backed coordinator
  changes also revoke mobile device sessions and refresh families.
- Privileged dashboard roles must complete TOTP enrollment before any dashboard
  session is issued. Recovery codes are high-entropy, hash-only, one-time
  factors. TOTP counters are replay-fenced.
- Destructive identity administration requires a recent MFA-authenticated
  access token. The browser retries the original operation once after step-up.

## Account-specific recovery boundary

| Account | Initial setup | Password change | Lost-password recovery |
| --- | --- | --- | --- |
| Dashboard manager/staff | `/auth/activate` invitation, then mandatory MFA enrollment | Authenticated `/auth/password/change` | Neutral `/auth/password/recovery/request`, expiring single-use link, then MFA |
| Coordinator | `/auth/activate`, then return to the coordinator client | Web or mobile authenticated password change | Dashboard recovery link; completion returns to the coordinator client and revokes dashboard and mobile sessions |
| Client Manager | Verified HTTPS `/gc/activate` link consumed only by Group Companion | Authenticated `/mobile/auth/password/change`; old mobile family is revoked before a replacement session is issued | Deliberately supervised: an authorized administrator uses `reset-password` to revoke all device sessions and issue a new one-time mobile reactivation link |

Client Managers are intentionally excluded from the dashboard recovery endpoint.
This prevents a mobile-only principal from crossing into the dashboard session
issuer. The browser `/gc/activate` page is only a safe app-link fallback: it
scrubs the credential from browser history and never accepts a password or
creates a dashboard session.

## Operational delivery boundary

The application creates, hashes, expires, consumes, supersedes, and audits the
link lifecycle. In development the authorized administrator can copy the
one-time link from the no-store response. Before production, delivery must be
wired to an approved transactional channel without logging link query strings.
Help-desk recovery must verify the requester under the organization's support
policy before an administrator resets MFA or reissues an invitation.
