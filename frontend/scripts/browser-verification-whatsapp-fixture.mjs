import assert from "node:assert/strict";
import { expect } from "@playwright/test";
import { isolatedPage, json } from "./browser-verification-local-fixture.mjs";

const createdAt = "2026-10-01T00:00:00Z";
export const groups = [
  { id: "synthetic-broadcast-a", name: "Synthetic International Partner Recognition Programme — November 2026" },
  { id: "synthetic-broadcast-b", name: "Other Synthetic Journey" },
].map(group => ({ ...group, recipient_count: 5, total_contact_count: 6, rejected_contact_count: 1, recipient_opt_in_confirmed: true,
  is_archived: false, created_at: createdAt, updated_at: createdAt, support_contacts: [{ id: "synthetic-support", name: "Synthetic Travel Operations", phone_number: "+12025550109" }],
  linked_client_groups: [{ id: "synthetic-submission", name: "Synthetic submissions", status: "active" }] }));
export const user = { id: "synthetic-admin", email: "admin@example.test", full_name: "Synthetic Administrator", role: "agency_admin", agency_id: "synthetic-agency", is_active: true, capabilities: [], created_at: createdAt, updated_at: createdAt };
const messageStatus = (message_type, status) => ({ message_type, status, already_sent: ["sent", "read", "delivered"].includes(status), latest_resend_status: null, resend_blocked: ["queued", "delivery_unknown"].includes(status), submitted_at: createdAt, status_updated_at: createdAt });
export const recipients = [
  { id: "synthetic-alex", name: "AlexandraSyntheticLongRecipientNameForResponsivePreviewVerification", welcome: "read", passport: "read" },
  { id: "synthetic-bruno", name: "Bruno Synthetic", welcome: "read", passport: "failed" },
  { id: "synthetic-casey", name: "Casey Synthetic", welcome: "failed", passport: "not_sent" },
  { id: "synthetic-dana", name: "Dana Synthetic", welcome: "queued", passport: "queued" },
  { id: "synthetic-elliot", name: "Elliot Synthetic", welcome: "read", passport: "delivery_unknown" },
].map((person, index) => ({ id: person.id, name: person.name, phone_number: `+1202555010${index}`, normalized_phone_number: `+1202555010${index}`,
  imported_fields: { department: index < 2 ? "Operations" : "Coordination" }, welcome_status: person.welcome, welcome_delivered: person.welcome === "read",
  message_statuses: [messageStatus("welcome", person.welcome), messageStatus("passport_link", person.passport)] }));
export const longLink = `https://travel.example.test/upload/${"synthetic-long-link-".repeat(7)}`;
const field = (key, label, kind = "textarea") => ({ key, label, kind, required: true, max_length: kind === "url" ? 2048 : 600 });
export const catalog = [
  { id: "welcome", message_type: "welcome", label: "Welcome message", description: "Introduce this synthetic journey.", category: "Getting started", image_required: true, audience: "standard", repeatable: false, fields: [field("message_content", "Welcome message")] },
  { id: "passport_link", message_type: "passport_link", label: "Passport link", description: "Share secure document instructions.", category: "Documents", image_required: true, audience: "standard", repeatable: false, fields: [field("passport_link", "Passport upload link", "url"), field("passport_intro", "Introduction"), field("message_content", "Instructions")] },
  { id: "reminder", message_type: "reminder", label: "Reminder", description: "Follow up with this journey's travellers.", category: "Follow-ups", image_required: false, audience: "reminder", repeatable: true, fields: [field("message_content", "Reminder message")] },
];
export const personalLink = recipient => `https://travel.example.test/private/${recipient.id}/synthetic-personal-token`;
export const savedMessage = (recipient, type) => `Dear ${recipient.name},\n${type === "passport_link" ? personalLink(recipient) : `Welcome to your ${recipient.id} journey.`}\nSaved for this recipient only.`;
const historyCounts = { all: 5, sent: 1, not_sent: 1, delivery_left: 1, failed: 3 };
export async function whatsappFixture(browser, origin, viewport, { freshAudience = false } = {}) {
  const state = { previews: [], sends: [], resends: [], media: [], holdPreview: false, releasePreview: null, holdSend: false, releaseSend: null, failSend: false, failResend: false, previewUnavailable: false, receipts: new Map(), acceptedKeys: new Set() };
  const people = freshAudience ? recipients.slice(0, 3).map(person => ({ ...person, welcome_status: undefined, welcome_delivered: undefined, message_statuses: [] })) : recipients;
  const forGroup = id => id === groups[0].id ? people : [{ ...recipients[0], id: "synthetic-other-person", name: "Other Group Passenger" }];
  const entry = (id, type = "passport_link") => ({ id, message_type: type, message_preview: "Synthetic saved message example", rendered_message: "Synthetic saved message example", created_at: createdAt, updated_at: createdAt, counts: historyCounts });
  const logs = (id, type) => forGroup(id).map((person, index) => ({ message_log_id: `saved-${type}-${person.id}`, recipient_id: person.id, name: person.name, phone_number: person.phone_number,
    current_phone_number: person.phone_number, status: ["sent", "failed", "delivery_unknown", "queued", "stalled"][index] ?? "sent", error_message: null,
    rendered_message: savedMessage(person, type), updated_at: createdAt, removed: false, can_resend: index < 2 }));
  const flow = await isolatedPage(browser, origin, viewport, async (route, request, url) => {
    const path = url.pathname, method = request.method();
    if (path === "/api/v1/whatsapp/groups" && method === "GET") { await json(route, groups); return true; }
    if (path === "/api/v1/whatsapp/message-catalog") { await json(route, catalog); return true; }
    const match = path.match(/^\/api\/v1\/whatsapp\/groups\/([^/]+)(.*)$/);
    if (match) {
      const [, id, suffix] = match, group = groups.find(group => group.id === id);
      if (!group) return false;
      if (!suffix && method === "GET") { await json(route, { ...group, recipients: forGroup(id) }); return true; }
      if (suffix === "/passenger-links") { await json(route, []); return true; }
      if (suffix === "/recipient-roster") {
        await json(route, { items: [{ kind: "rejected", display_order: 6, rejected_contact: { id: "synthetic-rejected", raw_name: "Rejected Synthetic", raw_phone_number: "invalid", reason: "Invalid synthetic number", reason_code: "invalid_phone", imported_fields: {}, created_at: createdAt, source_file_name: "synthetic.xlsx", sheet_name: "Contacts", row_number: 7 } }], counts: { all: 6, sent: 1, failed: 1, rejected: 1, replaced: 0, unidentified: 0 } }); return true;
      }
      if (suffix === "/preview" && method === "POST") {
        const draft = request.postDataJSON(); state.previews.push(draft);
        if (state.previewUnavailable) { await json(route, { detail: "Synthetic fresh preview unavailable after an uncertain send" }, 503); return true; }
        if (state.holdPreview) { state.holdPreview = false; await new Promise(resolve => { state.releasePreview = resolve; }); state.releasePreview = null; }
        const selected = forGroup(id).filter(person => draft.recipient_ids?.includes(person.id));
        const audience = draft.audience === "not_submitted" ? selected.filter(person => person.id !== recipients[0].id) : selected;
        const person = audience.find(person => person.id === draft.recipient_id) ?? audience[0] ?? forGroup(id)[0];
        const content = draft.message_content ?? `Please check the synthetic trip details for ${group.name}.`;
        const link = draft.passport_link ?? longLink, intro = draft.passport_intro ?? "Please complete your secure travel details.";
        await json(route, { message_type: draft.message_type, template_name: `synthetic_${draft.message_type}_v1`, recipient_id: person.id, recipient_name: person.name,
          recipient_count: forGroup(id).length, audience_recipient_ids: draft.audience === "not_submitted" ? forGroup(id).filter(person => person.id !== recipients[0].id).map(person => person.id) : undefined, eligible_recipient_count: audience.length,
          already_sent_count: 0, in_progress_count: 0, uncertain_recipient_count: 0, welcome_required_count: 0,
          message_content: content, passport_link: draft.message_type === "passport_link" ? link : null, passport_intro: draft.message_type === "passport_link" ? intro : null,
          rendered_message: `Dear ${person.name},\n\n${draft.message_type === "passport_link" ? `${intro}\n${link}\n` : ""}${content}`, header_image_id: null, content_source: "default", parameter_values: [content], header_parameter_values: [] }); return true;
      }
      if (suffix === "/welcome-media" && method === "POST") { state.media.push(request.postDataBuffer()?.length); await json(route, { media_id: "synthetic-header", file_name: "synthetic-header.png", content_type: "image/png" }); return true; }
      if (suffix === "/send" && method === "POST") {
        const body = request.postDataJSON(), key = request.headers()["idempotency-key"];
        assert.ok(key, "Current send carries an idempotency header"); assert.ok(!("recipient_id" in body) && !("resend_recipient_id" in body), "Preview sampling fields cannot enter dispatch");
        const record = { body, key, groupId: id }; state.sends.push(record);
        if (state.receipts.has(key)) assert.deepEqual(record, state.receipts.get(key), "Uncertain retry keeps exact reviewed payload and group"); else state.receipts.set(key, record);
        if (state.holdSend) { state.holdSend = false; await new Promise(resolve => { state.releaseSend = resolve; }); state.releaseSend = null; }
        if (state.failSend) { state.failSend = false; state.previewUnavailable = true; await route.abort("connectionreset"); return true; }
        state.acceptedKeys.add(key);
        await json(route, { batch_id: `synthetic-batch-${key}`, queued: body.recipient_ids.length, sent: 0, failed: 0, delivery_unknown: 0, skipped_already_sent: 0, skipped_in_progress: 0, skipped_delivery_unknown: 0 }); return true;
      }
      const resend = suffix.match(/^\/recipients\/([^/]+)\/resend$/);
      if (resend && method === "POST") {
        const body = request.postDataJSON(); assert.equal(id, groups[0].id); assert.equal(body.source_message_log_id, `saved-${body.message_type}-${resend[1]}`);
        state.resends.push({ recipientId: resend[1], groupId: id, body });
        if (state.failResend) { state.failResend = false; await route.abort("connectionreset"); return true; }
        await json(route, { queued: 1, sent: 0, failed: 0, delivery_unknown: 0 }); return true;
      }
      if (suffix === "/messages") { await json(route, { items: [entry("synthetic-passport"), entry("synthetic-welcome", "welcome")], total: 2, offset: 0, limit: 25 }); return true; }
      const message = suffix.match(/^\/messages\/([^/]+)(\/recipients)?$/);
      if (message) {
        const type = message[1] === "synthetic-welcome" ? "welcome" : "passport_link";
        if (!message[2]) { await json(route, entry(message[1], type)); return true; }
        const filter = url.searchParams.get("status_filter") ?? "all", search = (url.searchParams.get("q") ?? "").toLowerCase();
        const items = logs(id, type).filter(log => (filter === "all" || (filter === "sent" || filter === "delivery_left" ? log.status === "sent" : filter === "not_sent" ? log.status === "queued" : ["failed", "delivery_unknown", "stalled"].includes(log.status))) && `${log.name} ${log.current_phone_number}`.toLowerCase().includes(search));
        await json(route, { items, counts: historyCounts, total: items.length, offset: 0, limit: 50 }); return true;
      }
    }
    if (path.startsWith("/api/v1/whatsapp/activities/broadcast/")) { await json(route, { activity_id: path.split("/").at(-1), kind: "broadcast", title: "Synthetic send", context_label: groups[0].name, source_group_id: groups[0].id, total: 2, queued: 2, sent: 0, failed: 0, delivery_unknown: 0, started_at: createdAt, updated_at: createdAt }); return true; }
    return false;
  }, user);
  return { ...flow, state, people };
}
export async function openComposer(page, origin, definition) {
  await page.goto(`${origin.origin}/whatsapp`);
  await page.getByRole("link", { name: `Open ${groups[0].name}`, exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Broadcast sections" }).getByRole("link")).toHaveCount(5);
  await page.getByRole("button", { name: new RegExp(`^${definition.label} ${definition.description.replace(/[.*+?^$()|[\]\\]/g, "\\$&")}`) }).click();
  await expect(page.getByRole("heading", { name: definition.label, exact: true })).toBeVisible();
}
