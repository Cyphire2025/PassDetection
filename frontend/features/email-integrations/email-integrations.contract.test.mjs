import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const routes = read("../../constants/routes.ts");
const endpoints = read("../../lib/api/endpoints.ts");
const proxy = read("../../proxy.ts");
const roles = read("../../lib/utils/role-access.ts");
const sidebar = read("../../components/layout/sidebar.tsx");
const shell = read("./components/email-integrations-shell.tsx");
const connections = read("./components/connections-page.tsx");
const review = read("./components/review-queue-page.tsx");
const message = read("./components/message-activity-page.tsx");
const types = read("./types.ts");
const detailRoute = read(
  "../../app/(dashboard)/email-integrations/activity/[messageId]/page.tsx",
);

test("email integration routes and API endpoints are centralized", () => {
  assert.match(routes, /emailIntegrations: "\/email-integrations"/);
  assert.match(routes, /emailIntegrationsReview: "\/email-integrations\/review"/);
  assert.match(routes, /emailIntegrationsActivity: "\/email-integrations\/activity"/);
  assert.match(endpoints, /status: "\/api\/v1\/email-integrations\/status"/);
  assert.match(endpoints, /connections: "\/api\/v1\/email-integrations\/connections"/);
  assert.match(endpoints, /oauth\/gmail\/authorize/);
  assert.match(endpoints, /reviews\/\$\{reviewId\}\/resolve/);
  assert.match(endpoints, /messages\/\$\{messageId\}/);
});

test("email integration routes use both optimistic and direct role gates", () => {
  assert.match(proxy, /"\/email-integrations"/);
  const roleList = roles.match(
    /EMAIL_INTEGRATION_ROLES[\s\S]*?= \[([\s\S]*?)\];/,
  );
  assert.ok(roleList);
  assert.match(roleList[1], /"super_admin"/);
  assert.match(roleList[1], /"agency_admin"/);
  assert.match(roleList[1], /"agency_manager"/);
  assert.doesNotMatch(roleList[1], /"agency_staff"/);
  assert.doesNotMatch(roleList[1], /"agency_coordinator"/);
  assert.match(shell, /canAccessEmailIntegrations\(role\)/);
  assert.match(shell, /router\.replace\(/);
  assert.match(shell, /if \(!hasHydrated \|\| !canAccess\) return null/);
});

test("sidebar and section navigation expose accessible normal links", () => {
  const emailNav = sidebar
    .split("\n")
    .find((line) => line.includes('label: "Email Integrations"'));
  assert.ok(emailNav);
  assert.match(emailNav, /icon: Mail/);
  assert.match(emailNav, /"super_admin", "agency_admin", "agency_manager"/);
  assert.match(shell, /<Link/);
  assert.match(shell, /aria-current=\{isActive \? "page" : undefined\}/);
  assert.doesNotMatch(shell, /role="tab"/);
});

test("OAuth handoff never stores credentials in browser-managed storage", () => {
  assert.match(connections, /window\.location\.assign\(authorizationUrl\)/);
  assert.match(connections, /isSafeOAuthAuthorizationUrl\(authorizationUrl\)/);
  assert.doesNotMatch(connections, /connection\.agency_name/);
  for (const source of [connections, review, message, types]) {
    assert.doesNotMatch(source, /localStorage|sessionStorage/);
    assert.doesNotMatch(source, /access_token|refresh_token|client_secret/);
  }
});

test("review decisions are revision-safe and email content renders as text", () => {
  assert.match(review, /expected_revision: item\.revision/);
  assert.match(review, /action: "assign"/);
  assert.match(message, /\{data\.body_excerpt \|\|/);
  assert.match(message, /whitespace-pre-wrap/);
  assert.doesNotMatch(review, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(message, /dangerouslySetInnerHTML/);
});

test("review queue exposes full history and confirms whole-email unrelated scope", () => {
  const statusList = review.match(
    /const REVIEW_STATUSES = \[([\s\S]*?)\] as const;/,
  );
  assert.ok(statusList);
  for (const status of [
    "open",
    "deferred",
    "resolved",
    "rejected",
    "cancelled",
    "all",
  ]) {
    assert.match(statusList[1], new RegExp(`value: "${status}"`));
  }
  assert.match(review, /Mark this entire email as unrelated\?/);
  assert.match(review, /entire source email as unrelated/);
  assert.match(review, /all other open or deferred review items/);
});

test("message detail route follows the Next 16 asynchronous params contract", () => {
  assert.match(detailRoute, /params: Promise<\{ messageId: string \}>/);
  assert.match(detailRoute, /const \{ messageId \} = await params/);
});

test("connection response type contains only the public contract fields", () => {
  const connection = types.match(
    /export interface EmailConnection \{([\s\S]*?)\n\}/,
  );
  assert.ok(connection);
  for (const field of [
    "id",
    "agency_id",
    "agency_name",
    "provider",
    "email_address",
    "status",
    "last_successful_sync_at",
    "last_sync_attempt_at",
    "last_error_message",
    "allowed_actions",
  ]) {
    assert.match(connection[1], new RegExp(`\\b${field}\\b`));
  }
  assert.doesNotMatch(connection[1], /token|secret|authorization_code/);
});
