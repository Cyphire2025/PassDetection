import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const endpoints = read("../../lib/api/endpoints.ts");
const routes = read("../../constants/routes.ts");
const header = read("../../components/layout/header.tsx");
const api = read("./api/notifications.api.ts");
const hooks = read("./hooks/use-notifications.ts");
const liveHistory = read("../../lib/hooks/use-live-history-feed.ts");
const bell = read("./components/notification-bell.tsx");
const navigation = read("./utils/notification-navigation.ts");
const types = read("./types.ts");

test("notification feed and mutation endpoints are centralized and typed", () => {
  assert.match(endpoints, /feed: "\/api\/v1\/notifications\/feed"/);
  assert.match(
    endpoints,
    /`\/api\/v1\/notifications\/\$\{encodeURIComponent\(notificationId\)\}\/read`/,
  );
  assert.match(endpoints, /readAll: "\/api\/v1\/notifications\/read-all"/);
  assert.match(api, /NotificationFeedResponse/);
  assert.match(api, /unread_only: unreadOnly \|\| undefined/);
  assert.match(api, /priority,/);
  assert.match(api, /limit,/);
  assert.match(api, /cursor,/);
  for (const field of [
    "id",
    "type",
    "title",
    "message",
    "entity_type",
    "entity_id",
    "priority",
    "category",
    "is_read",
    "created_at",
    "metadata",
  ]) {
    assert.match(types, new RegExp(`\\b${field}\\b`));
  }
});

test("persistent header renders an accessible notification dialog", () => {
  assert.match(header, /import \{ NotificationBell \}/);
  assert.match(header, /<NotificationBell \/>/);
  assert.match(bell, /aria-haspopup="dialog"/);
  assert.match(bell, /aria-expanded=\{isOpen\}/);
  assert.match(bell, /role="dialog"/);
  assert.match(bell, /aria-modal="true"/);
  assert.match(bell, /aria-label="Close notifications"/);
  assert.match(bell, /event\.key === "Escape"/);
  assert.match(bell, /event\.key !== "Tab"/);
  assert.match(bell, /Mark all read/);
  assert.match(bell, /onMarkRead/);
  assert.match(bell, /markRead\.isError \|\| markAllRead\.isError/);
  assert.match(bell, /role="alert"/);
  assert.match(hooks, /mutationFn: notificationsApi\.markRead,\s*onSettled: invalidate/);
  assert.match(hooks, /mutationFn: notificationsApi\.markAllRead,\s*onSettled: invalidate/);
});

test("notification polling is user scoped, visibility aware, and recoverable", () => {
  assert.match(hooks, /root: \(userId: string\)/);
  assert.match(hooks, /"notifications",\s*userId,\s*"feed"/);
  assert.match(hooks, /const CLOSED_REFRESH_INTERVAL_MS = 15_000/);
  assert.match(hooks, /const OPEN_REFRESH_INTERVAL_MS = 5_000/);
  assert.match(hooks, /useLiveHistoryFeed<NotificationFeedResponse>/);
  assert.match(liveHistory, /refetchIntervalInBackground: false/);
  assert.match(liveHistory, /refetchOnWindowFocus: true/);
  assert.match(liveHistory, /refetchOnReconnect: "always"/);
  assert.match(hooks, /enabled: Boolean\(userId\)/);
});

test("notification history is bounded and never polled with the live head", () => {
  assert.match(liveHistory, /queryKey: \[\.\.\.queryKey, "live"\]/);
  assert.match(liveHistory, /const historyKey = \[\.\.\.queryKey, "history", startCursor\]/);
  assert.match(liveHistory, /maxPages: 5/);
  assert.match(liveHistory, /staleTime: Infinity/);
  assert.match(liveHistory, /refetchOnWindowFocus: false/);
  assert.match(liveHistory, /refetchOnReconnect: false/);
  assert.match(liveHistory, /refetchOnMount: false/);
  assert.match(liveHistory, /meta: \{ historyOnly: true \}/);
  assert.match(liveHistory, /const seen = new Set<string>\(\)/);
});

test("notification navigation accepts only known entity types and safe ids", () => {
  assert.match(
    navigation,
    /const SAFE_ENTITY_ID = \/\^\[A-Za-z0-9_-\]\{1,128\}\$\//,
  );
  assert.match(navigation, /case "email_message"/);
  assert.match(navigation, /case "passport"/);
  assert.match(navigation, /case "document_group"/);
  assert.match(navigation, /case "rooming_group"/);
  assert.match(navigation, /default:\s*return null/);
  assert.match(navigation, /if \(!entityId \|\| !SAFE_ENTITY_ID\.test\(entityId\)\)/);
  assert.doesNotMatch(navigation, /window\.location|metadata.*(?:url|href)/i);
  assert.doesNotMatch(bell, /dangerouslySetInnerHTML|window\.location/);
});

test("notification filters and inbox destination stay inside known routes", () => {
  for (const filter of ["All", "Unread", "Critical", "High"]) {
    assert.match(bell, new RegExp(`label: "${filter}"`));
  }
  assert.match(routes, /emailIntegrationsInbox: "\/email-integrations\/inbox"/);
  assert.match(routes, /emailIntegrations: "\/email-integrations"/);
  assert.match(bell, /ROUTES\.dashboard\.emailIntegrationsInbox/);
  assert.match(bell, /ROUTES\.dashboard\.emailIntegrations/);
  assert.match(bell, /Notification settings/);
  assert.match(navigation, /ROUTES\.dashboard\.emailIntegrationsInbox/);
});

test("notification rows render provider, account, and group metadata", () => {
  assert.match(
    bell,
    /readNotificationMetadata\(notification\.metadata, "account_email"\)/,
  );
  assert.match(
    bell,
    /readNotificationMetadata\(notification\.metadata, "email_address"\)/,
  );
  assert.match(
    bell,
    /readNotificationMetadata\(notification\.metadata, "provider"\)/,
  );
  assert.match(
    bell,
    /readNotificationMetadata\(notification\.metadata, "group_name"\)/,
  );
  assert.match(bell, /<NotificationContent[\s\S]*?account=\{account\}/);
  assert.match(bell, /provider=\{provider\}/);
  assert.match(bell, /group=\{group\}/);
  assert.match(
    bell,
    /\[provider && formatCategory\(provider\), account, group\]/,
  );
});
