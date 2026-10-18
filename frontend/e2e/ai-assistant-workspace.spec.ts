import { expect, test, type Page } from "@playwright/test";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";

const timestamp = "2026-10-18T00:00:00Z";
const conversationId = "b6c548e0-6e77-4d1b-b107-6799b9d31201";
const images = [1, 2, 3].map((number) => ({ id: `b6c548e0-6e77-4d1b-b107-6799b9d3120${number}`,
  name: `Travel inspiration ${number}`, mime: "image/png", size: 1024, kind: "generated", created_at: timestamp,
  url: `/api/v1/ai-assistant/assets/b6c548e0-6e77-4d1b-b107-6799b9d3120${number}/content` }));
const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aC1sAAAAASUVORK5CYII=", "base64");
const file = { ...images[0], id: "b6c548e0-6e77-4d1b-b107-6799b9d31209", name: "Departure plan.txt", mime: "text/plain", kind: "uploaded" };
const responseText = "There are **3 pending documents**.\n\n| Group | Pending |\n| --- | --- |\n| Synthetic departure | 3 |\n\nChecked the current dashboard records.";

function stream(events: object[]) { return events.map((event) => `event: assistant\ndata: ${JSON.stringify(event)}\n\n`).join(""); }

function wave() {
  const rate = 16000; const samples = rate * 24; const data = Buffer.alloc(44 + samples * 2);
  data.write("RIFF"); data.writeUInt32LE(data.length - 8, 4); data.write("WAVEfmt ", 8); data.writeUInt32LE(16, 16);
  data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22); data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28);
  data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34); data.write("data", 36); data.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index++) data.writeInt16LE(Math.round(Math.sin(index / rate * Math.PI * 360) * (index < rate ? 1800 : 14000)), 44 + index * 2);
  return data;
}

async function workspace(page: Page, speech = false) {
  await page.route("**/api/v1/ai-assistant/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status")) return route.fulfill({ json: { configured: true, speech_configured: speech, model: "gpt-6-luna", reasoning_effort: "high", access: "read_only", name: "Synthetic administrator" } });
    if (path.endsWith("/live")) return route.fulfill({ json: { observed_at: timestamp, agencies: [] } });
    if (path.endsWith("/attachments")) return route.fulfill({ json: file });
    if (path.endsWith("/transcribe")) return route.fulfill({ json: { text: "Which documents are still pending?" } });
    if (path.endsWith("/content")) return route.fulfill({ contentType: "image/png", body: tinyPng });
    if (path.endsWith("/assets")) return route.fulfill({ json: { items: images, next_cursor: null } });
    if (path.endsWith("/conversations")) return route.fulfill({ json: { items: [{ id: conversationId, title: "A saved departure plan", created_at: timestamp }], next_cursor: null } });
    if (path.includes("/conversations/")) return route.fulfill({ json: { items: [{ id: "saved-turn", user: "What is pending?", assistant: responseText, created_at: timestamp, images: [], sources: [] }], next_cursor: null } });
    if (path.endsWith("/speech")) return route.fulfill({ contentType: "audio/wav", body: wave() });
    if (path.endsWith("/chat")) {
      const body = route.request().postDataJSON();
      const imageEvents = body.mode === "image" ? images.map((image) => ({ type: "image", image })) : [];
      return route.fulfill({ contentType: "text/event-stream", body: stream([
        { type: "status", message: "Checking current dashboard records", phase: "thinking" }, ...imageEvents,
        { type: "text_delta", text: body.mode === "image" ? "Created three images." : responseText.slice(0, 40) },
        ...(body.mode === "image" ? [] : [{ type: "text_delta", text: responseText.slice(40) }, { type: "source", source: { view: "document_review", observed_at: timestamp, completeness: "complete" } }]),
        { type: "done", request_id: body.request_id },
      ]) });
    }
    return route.fulfill({ status: 404, json: { detail: "Unknown synthetic fixture endpoint" } });
  });
}

test("typed questions, file attachments, source labels and saved history work together", async ({ page }, testInfo) => {
  await workspace(page);
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/ai");
  await page.getByRole("button", { name: "Add files or create images" }).click();
  await expect(page.getByRole("button", { name: /Add files.*PDF/ })).toBeEnabled();
  await page.getByLabel("Upload attachments").setInputFiles({ name: "Departure plan.txt", mimeType: "text/plain", buffer: Buffer.from("Synthetic departure: three documents pending.") });
  await expect(page.getByRole("button", { name: "Detach Departure plan.txt" })).toBeVisible();
  await page.getByRole("textbox", { name: "Message Global Connects" }).fill("What documents are still pending?");
  const request = page.waitForRequest((request) => request.url().endsWith("/ai-assistant/chat"));
  await page.getByRole("button", { name: "Send message" }).click();
  expect((await request).postDataJSON().attachment_ids).toEqual([file.id]);
  await expect(page.getByRole("table")).toContainText("Synthetic departure");
  await expect(page.getByText("document review", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy reply" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("ai-conversation-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Open conversations" }).click();
  await page.getByRole("button", { name: /A saved departure plan/ }).click();
  await expect(page.getByText("What is pending?", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ai-conversation-mobile.png"), fullPage: true });
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 403, json: { detail: "Access revoked" } }));
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).not.toBeAttached();
  await expect(page.getByText("Administrator access is needed for this workspace.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("image generation reveals from the sculpture, selects thumbnails and returns to its origin", async ({ page }, testInfo) => {
  test.setTimeout(120000); // Software WebGL readbacks are slower than the browser's animation clock.
  await workspace(page);
  await page.goto("/ai");
  await page.getByRole("button", { name: "Add files or create images" }).click();
  await page.getByRole("button", { name: /Create images.*Bring an idea/ }).click();
  await page.getByRole("combobox", { name: "Number of images" }).selectOption("3");
  await page.getByRole("textbox", { name: "Describe your image" }).fill("Create three elegant travel inspirations");
  await page.getByRole("button", { name: "Create images", exact: true }).click();
  const reveal = page.getByTestId("image-reveal");
  await expect(reveal).toBeVisible();
  await expect.poll(() => reveal.evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--reveal")))).toBe(1);
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
  await expect(page.getByRole("button", { name: "Select Travel inspiration 1" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Select Travel inspiration 3" }).click();
  await expect(page.getByRole("region", { name: "Image viewer: Travel inspiration 3" })).toBeVisible();
  const frame = await page.getByRole("region", { name: "Image viewer: Travel inspiration 3" }).boundingBox();
  expect(frame!.height / frame!.width).toBeGreaterThan(.55);
  await page.screenshot({ path: testInfo.outputPath("ai-image-reveal.png"), fullPage: true });
  await page.getByRole("button", { name: "Close image", exact: true }).click();
  await expect(reveal).not.toBeAttached();
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("dialog", { name: "Your library" })).toBeVisible();
  await page.getByRole("button", { name: "View Travel inspiration 2" }).click();
  await expect(page.getByRole("region", { name: "Image viewer: Travel inspiration 2" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(reveal).not.toBeAttached();
});

test("spoken output drives the actual playback analyser and can be interrupted", async ({ page }) => {
  test.setTimeout(90000);
  await workspace(page, true);
  await page.goto("/ai");
  await page.getByRole("textbox", { name: "Message Global Connects" }).fill("Give me a short spoken overview");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("button", { name: "Stop speaking" })).toBeVisible();
  await expect(page.locator("main[data-phase='speaking']")).toBeVisible();
  await expect.poll(() => page.getByTestId("assistant-voice-status").evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--voice-level")))).toBeGreaterThan(.1);
  await page.getByRole("button", { name: "Stop speaking" }).click();
  await expect(page.locator("main[data-phase='idle']")).toBeVisible();
});

test("denied administrator access keeps company information and uploads unavailable", async ({ page }) => {
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 403, json: { detail: "Administrator access required" } }));
  await page.goto("/ai");
  await expect(page.getByText("Administrator access is needed for this workspace.")).toBeVisible();
  await page.getByRole("textbox", { name: "Message Global Connects" }).fill("Show passenger data");
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  await page.getByRole("button", { name: "Add files or create images" }).click();
  await expect(page.getByRole("button", { name: /Add files.*PDF/ })).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("link", { name: "Sign in to Global Connects" })).toBeVisible();
});

test("anonymous visitors keep the local voice preview without staff session refresh or navigation", async ({ page }) => {
  const refreshes: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/auth/refresh")) refreshes.push(request.url()); });
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 401, json: { detail: "Authentication required" } }));
  await syntheticMicrophone(page);
  await page.goto("/ai");
  await expect(page.getByText("Sign in to ask about your Global Connects workspace.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", "/session-restore?from=%2Fai");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  expect(new URL(page.url()).pathname).toBe("/ai");
  expect(refreshes).toEqual([]);
});

test("a spoken question is transcribed, answered in chat, and microphone cancellation discards audio", async ({ page }) => {
  test.setTimeout(90000);
  await workspace(page);
  await syntheticMicrophone(page);
  await page.goto("/ai");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.evaluate(() => (window as unknown as { __voiceTest: { setVolume: (value: number) => void } }).__voiceTest.setVolume(.22));
  await expect.poll(() => page.getByTestId("assistant-voice-status").evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--voice-level")))).toBeGreaterThan(.5);
  const transcribed = page.waitForRequest((request) => request.url().endsWith("/ai-assistant/transcribe"));
  await page.getByRole("button", { name: "Finish voice message" }).click();
  expect((await transcribed).postDataBuffer()!.length).toBeGreaterThan(100);
  await expect(page.getByRole("table")).toContainText("Synthetic departure");
  await expect(page.getByText("Which documents are still pending?", { exact: true })).toBeVisible();
  const laterUploads: string[] = [];
  page.on("request", (request) => { if (request.url().endsWith("/ai-assistant/transcribe")) laterUploads.push(request.url()); });
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "Finish voice message" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(laterUploads).toEqual([]);
});
