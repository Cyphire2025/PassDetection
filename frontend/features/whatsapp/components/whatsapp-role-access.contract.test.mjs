import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const roleAccess = readFileSync(
  new URL("../../../lib/utils/role-access.ts", import.meta.url),
  "utf8",
);
const sidebar = readFileSync(
  new URL("../../../components/layout/sidebar.tsx", import.meta.url),
  "utf8",
);
const whatsappPage = readFileSync(
  new URL("../../../app/(dashboard)/whatsapp/page.tsx", import.meta.url),
  "utf8",
);
const createLinkModal = readFileSync(
  new URL("../../passports/components/create-upload-link-modal.tsx", import.meta.url),
  "utf8",
);
const groupDetail = readFileSync(
  new URL("../../passports/components/passport-group-detail.tsx", import.meta.url),
  "utf8",
);
const tracking = readFileSync(
  new URL("../../passports/components/group-whatsapp-broadcast-panel.tsx", import.meta.url),
  "utf8",
);

test("WhatsApp broadcast capability excludes staff", () => {
  const roleList = roleAccess.match(
    /WHATSAPP_BROADCAST_ROLES[\s\S]*?= \[([\s\S]*?)\];/,
  );
  assert.ok(roleList);
  assert.match(roleList[1], /"super_admin"/);
  assert.match(roleList[1], /"agency_admin"/);
  assert.match(roleList[1], /"agency_manager"/);
  assert.doesNotMatch(roleList[1], /"agency_staff"/);
});

test("staff never sees the WhatsApp navigation or group integration", () => {
  const whatsappNav = sidebar
    .split("\n")
    .find((line) => line.includes('label: "WhatsApp"'));
  assert.ok(whatsappNav);
  assert.doesNotMatch(whatsappNav, /agency_staff/);
  assert.match(createLinkModal, /\{canAccessWhatsApp && \(\s*<WhatsAppBroadcastSelector/);
  assert.match(groupDetail, /\{canAccessWhatsApp && \(\s*<GroupWhatsAppBroadcastPanel/);
});

test("direct WhatsApp routes redirect roles without broadcast access", () => {
  assert.match(whatsappPage, /canAccessWhatsAppBroadcasts\(role\)/);
  assert.match(whatsappPage, /router\.replace\(/);
  assert.match(tracking, /canAccessWhatsAppBroadcasts\(role\)/);
  assert.match(tracking, /if \(!hasHydrated \|\| !canAccessWhatsApp\) return null/);
});
