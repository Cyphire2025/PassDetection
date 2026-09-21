import { expect, test, type Page, type Route } from "@playwright/test";
import sharp from "sharp";
import type { WhatsAppBroadcastGroupDetail, WhatsAppMessageDraft } from "../features/whatsapp/api/whatsapp.api";

const inviteLink = "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv?mode=ac_t";
const inviteMessage = "Please join our official WhatsApp group for travel updates and schedules.";
const renderedMessage = (message: string, link: string) => `Dear Delegates\n\nGreetings from Global Connect Travels\n\n${message}\n\n${link}\n\nRegards\nTeam Global Connect Travels`;

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockInviteApi(page: Page) {
  const staff = { id: "invite-staff", email: "invite@example.test", full_name: "Invite Test Staff", role: "agency_staff", agency_id: "invite-agency", is_active: true, capabilities: [] };
  const group: WhatsAppBroadcastGroupDetail = {
    id: "invite-broadcast", name: "September delegates", is_archived: false, archived_at: null,
    created_at: "2026-09-20T09:00:00Z", updated_at: "2026-09-20T09:00:00Z",
    recipient_count: 2, total_contact_count: 2, recipient_opt_in_confirmed: true,
    support_contacts: [], rejected_contact_count: 0,
    recipients: ["Passenger A", "Passenger B"].map((name, index) => ({
      id: `recipient-${index}`, name, phone_number: `+91999999999${index}`, normalized_phone_number: `+91999999999${index}`,
      welcome_delivered: true, welcome_status: "delivered", imported_fields: {}, message_statuses: [],
    })),
  };
  const previews: WhatsAppMessageDraft[] = [];
  const sends: WhatsAppMessageDraft[] = [];
  const uploads: string[] = [];
  const unexpectedMutations: string[] = [];
  await page.context().addCookies([{ name: "access_token", value: "e2e-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user: staff, token_type: "bearer", access_token_expires_at: "2099-09-19T13:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, staff);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/whatsapp/groups" && request.method() === "GET") return json(route, url.searchParams.get("archived") === "true" ? [] : [group]);
    if (path === "/api/v1/whatsapp/groups/invite-broadcast" && request.method() === "GET") return json(route, group);
    if (path === "/api/v1/whatsapp/groups/invite-broadcast/preview" && request.method() === "POST") {
      const body = request.postDataJSON() as WhatsAppMessageDraft;
      previews.push(body);
      const message = body.message_content ?? inviteMessage;
      const link = body.group_invite_link ?? "";
      return json(route, {
        message_type: "group_invite", template_name: "whatsapp_group_invite_v1", recipient_id: body.recipient_id ?? "recipient-0", recipient_name: "Passenger A",
        recipient_count: 2, eligible_recipient_count: body.recipient_ids?.length ?? 2,
        already_sent_count: 0, in_progress_count: 0, uncertain_recipient_count: 0, welcome_required_count: 0,
        passport_intro: null, passport_link: null, message_content: message, group_invite_link: link,
        header_image_id: body.header_image_id ?? null, content_source: "default", header_parameter_values: body.header_image_id ? [body.header_image_id] : [], parameter_values: [message, link],
        rendered_message: renderedMessage(message, link || "[WhatsApp group invite link]"),
      });
    }
    if (path === "/api/v1/whatsapp/groups/invite-broadcast/welcome-media" && request.method() === "POST") {
      uploads.push(request.headers()["content-type"]);
      return json(route, { media_id: "uploaded-invite-photo", file_name: "invite.png", content_type: "image/png" });
    }
    if (path === "/api/v1/whatsapp/groups/invite-broadcast/send" && request.method() === "POST") {
      const body = request.postDataJSON() as WhatsAppMessageDraft;
      sends.push(body);
      return json(route, { batch_id: "invite-batch", queued: body.recipient_ids?.length ?? 2, sent: 0, failed: 0, delivery_unknown: 0, skipped_already_sent: 0, skipped_in_progress: 0, skipped_delivery_unknown: 0, results: [] });
    }
    if (path === "/api/v1/whatsapp/activities/broadcast/invite-batch") return json(route, {
      activity_id: "invite-batch", kind: "broadcast", title: "Group invite broadcast", context_label: group.name, source_group_id: group.id, document_type: null,
      total: 2, queued: 2, sent: 0, failed: 0, delivery_unknown: 0, started_at: "2026-09-20T09:00:00Z", updated_at: "2026-09-20T09:00:00Z",
    });
    if (request.method() === "GET") return json(route, []);
    unexpectedMutations.push(`${request.method()} ${path}`);
    return json(route, { detail: "Unexpected API request in isolated invite test." }, 400);
  });
  return { previews, sends, uploads, unexpectedMutations };
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1080 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`staff can edit, preview and queue a group invite on ${viewport.name}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const api = await mockInviteApi(page);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.setViewportSize(viewport);
    await page.goto("/whatsapp");
    await page.getByRole("button", { name: "Open actions for September delegates" }).filter({ visible: true }).click();
    await page.getByRole("button", { name: "Send group invite", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Send Group Invite" });
    await expect(dialog).toBeVisible();
    const messageInput = dialog.getByRole("textbox", { name: "Invitation message", exact: true });
    const linkInput = dialog.getByRole("textbox", { name: "WhatsApp group invite link", exact: true });
    const sendButton = dialog.getByRole("button", { name: /^Send individually to/ });
    await expect(sendButton).toBeDisabled();
    await messageInput.fill("Join our September delegates group for the final travel schedule.");
    await linkInput.fill("https://example.com/not-a-whatsapp-group");
    await expect(sendButton).toBeDisabled();
    await linkInput.fill(inviteLink);
    const preview = dialog.getByTestId("whatsapp-message-preview");
    await expect(preview).toHaveText(renderedMessage("Join our September delegates group for the final travel schedule.", inviteLink));
    await expect(sendButton).toBeDisabled();
    const imageInput = dialog.locator('input[type="file"]');
    await expect(imageInput).toHaveCount(1);
    const imageBytes = await sharp({ create: { width: 640, height: 360, channels: 3, background: { r: 30, g: 140, b: 170 } } }).png().toBuffer();
    await imageInput.setInputFiles({ name: "invite.png", mimeType: "image/png", buffer: imageBytes });
    await expect(dialog.getByRole("img", { name: "Selected Group invite image header" })).toBeVisible();
    await expect.poll(() => dialog.getByRole("img", { name: "Selected Group invite image header" }).evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(640);
    await expect(sendButton).toBeEnabled();
    await expect(dialog).not.toContainText("Passport upload link");
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const screenshot = testInfo.outputPath(`whatsapp-group-invite-${viewport.name}.png`);
    await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });
    await testInfo.attach(`Group invite composer — ${viewport.name}`, { path: screenshot, contentType: "image/png" });
    await preview.scrollIntoViewIfNeeded();
    await expect(preview).toBeVisible();
    await expect(sendButton).toBeVisible();
    if (viewport.name === "mobile") {
      const previewScreenshot = testInfo.outputPath("whatsapp-group-invite-mobile-preview.png");
      await page.screenshot({ path: previewScreenshot, animations: "disabled", fullPage: true });
      await testInfo.attach("Mobile invitation preview", { path: previewScreenshot, contentType: "image/png" });
    }
    await sendButton.click();
    await expect(dialog).toHaveCount(0);
    expect(api.sends).toHaveLength(1);
    expect(api.sends[0]).toMatchObject({ message_type: "group_invite", message_content: "Join our September delegates group for the final travel schedule.", group_invite_link: inviteLink, header_image_id: "uploaded-invite-photo" });
    expect(api.uploads).toHaveLength(1);
    expect(api.uploads[0]).toContain("multipart/form-data");
    expect(api.previews.at(-1)).toMatchObject({ message_type: "group_invite", group_invite_link: inviteLink });
    expect(api.unexpectedMutations).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
}
