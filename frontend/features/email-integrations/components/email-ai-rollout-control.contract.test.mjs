import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const component = read("./email-ai-rollout-control.tsx");
const connections = read("./connections-page.tsx");
const api = read("../api/email-integrations.api.ts");
const hooks = read("../hooks/use-email-integrations.ts");
const types = read("../types.ts");
const endpoints = read("../../../lib/api/endpoints.ts");

test("rollout API mirrors the revision-safe SuperAdmin contract", () => {
  assert.match(
    endpoints,
    /emailAiRollout: "\/api\/v1\/admin\/email-ai-rollout"/,
  );
  assert.match(api, /rolloutTargets:/);
  assert.match(api, /scope_type: scopeType/);
  assert.match(api, /search: search \|\| undefined/);
  assert.match(api, /updateRolloutPolicy:/);
  assert.match(api, /apiClient\.put<EmailAiRolloutTarget>/);
  assert.match(types, /"agency" \| "user" \| "connection"/);
  for (const field of [
    "direct_enabled",
    "effective_enabled",
    "global_enabled",
    "global_notifications_enabled",
    "expected_updated_at",
    "truncated",
  ]) {
    assert.match(types, new RegExp(`\\b${field}\\b`));
  }
});

test("rollout reads are user scoped and mutations always recover fresh state", () => {
  assert.match(hooks, /rolloutRoot: \(userId: string\)/);
  assert.match(hooks, /"ai-rollout",\s*userId/);
  assert.match(hooks, /enabled: Boolean\(userId\) && enabled/);
  assert.match(hooks, /refetchOnWindowFocus: true/);
  assert.match(hooks, /useUpdateEmailAiRolloutPolicy/);
  assert.match(hooks, /onSettled:/);
  assert.match(hooks, /EMAIL_INTEGRATION_QUERY_KEYS\.rolloutRoot\(userId\)/);
});

test("the Connections page and card both fail closed for non-SuperAdmins", () => {
  assert.match(connections, /role === "super_admin"/);
  assert.match(connections, /<EmailAiRolloutControl \/>/);
  assert.match(component, /user\?\.role === "super_admin"/);
  assert.match(component, /if \(!isSuperAdmin\) return null/);
  assert.match(
    component,
    /useEmailAiRolloutTargets\([\s\S]*?isSuperAdmin,/,
  );
});

test("nontechnical controls explain direct, inherited, and effective state", () => {
  for (const label of [
    "Agencies",
    "Users",
    "My mailboxes",
    "Rule at this level",
    "Effective state",
    "Inherited",
    "Allowed here",
    "Paused here",
    "Rollout allowed",
    "Rollout paused",
  ]) {
    assert.match(component, new RegExp(label));
  }
  assert.match(component, /Control one of your connected mailboxes/);
  assert.doesNotMatch(component, /"AI allowed"|"AI paused"/);
  assert.match(component, /nextEnabled \? "Allow" : "Pause"/);
  assert.match(component, /decision\.enabled \? "Allow" : "Pause"/);
  assert.match(component, /global\s+or parent pause always wins/i);
  assert.match(component, /mailbox owner must still\s+opt in/);
});

test("global and truncated states remain visible and actionable", () => {
  assert.match(component, /!targets\.data\.global_enabled/);
  assert.match(component, /Travel AI is globally paused/);
  assert.match(component, /global_notifications_enabled/);
  assert.match(component, /targets\.data\?\.truncated/);
  assert.match(component, /Only the first matching results are shown/);
  assert.match(component, /maxLength=\{120\}/);
  assert.match(component, /expected_updated_at: decision\.target\.updated_at/);
});

test("rollout mutations are confirmed, pending-safe, and render only text", () => {
  assert.match(component, /<EmailDialog/);
  assert.match(component, /isBusy=\{updatePolicy\.isPending\}/);
  assert.match(component, /disabled=\{updatePolicy\.isPending\}/);
  assert.match(component, /does not send messages/);
  assert.match(component, /mailbox write access/);
  assert.doesNotMatch(component, /dangerouslySetInnerHTML|localStorage|sessionStorage/);
});

test("a stale rollout decision closes and recovers from fresh server state", () => {
  assert.match(component, /error\.code === "HTTP_409"/);
  assert.match(
    component,
    /onError:[\s\S]*?isRolloutConflict\(error\)[\s\S]*?setDecision\(null\)/,
  );
  assert.match(component, /latest settings are being refreshed/i);
  assert.match(component, /review the current state before trying again/i);
  assert.match(hooks, /onSettled:/);
});
