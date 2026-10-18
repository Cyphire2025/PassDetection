import { expect, test, type Page } from "@playwright/test";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { assistantAuth } from "./support/assistant-auth";
import { sculptureBoundary } from "./support/sculpture-boundary";
import { observeSculpture, sculptureSignal } from "./support/sculpture-signal";

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
  await assistantAuth(page);
  await page.route("**/api/v1/ai-assistant/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status")) return route.fulfill({ json: { configured: true, speech_configured: speech, model: "gpt-6-luna", reasoning_effort: "high", access: "read_only", name: "Synthetic administrator", account_id: "workspace-admin", account_scope: "super_admin" } });
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
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByRole("table")).toContainText("Synthetic departure");
  await expect(page.getByText("document review", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy reply" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("ai-conversation-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Open conversations" }).click();
  await page.getByRole("button", { name: /^A saved departure plan/ }).click();
  await expect(page.getByText("What is pending?", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ai-conversation-mobile.png"), fullPage: true });
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 403, json: { detail: "Access revoked" } }));
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).not.toBeAttached();
  await expect(page.getByRole("heading", { name: "AI access is unavailable" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("image generation reveals from the sculpture, selects thumbnails and returns to its origin", async ({ page }, testInfo) => {
  test.setTimeout(120000); // Software WebGL readbacks are slower than the browser's animation clock.
  await workspace(page);
  await page.emulateMedia({ colorScheme: "dark" });
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
  const first = await sculptureBoundary(page, true);
  await page.waitForTimeout(1000); // Compare the settled perimeter at two animation times.
  const moving = await sculptureBoundary(page, true);
  expect(moving.edgePixels.equals(first.edgePixels)).toBe(false);
  await page.getByRole("button", { name: "Switch to light mode" }).click();
  await sculptureBoundary(page, false);
  await page.screenshot({ path: testInfo.outputPath("ai-image-reveal-light.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await sculptureBoundary(page, false);
  await page.screenshot({ path: testInfo.outputPath("ai-image-reveal-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "Close image", exact: true }).click();
  await expect(reveal).not.toBeAttached();
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("dialog", { name: "Your library" })).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "View Travel inspiration 2" }).click();
  await expect(page.getByRole("region", { name: "Image viewer: Travel inspiration 2" })).toBeVisible();
  await expect.poll(() => reveal.evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--reveal")))).toBe(1);
  await sculptureBoundary(page, false);
  await page.keyboard.press("Escape");
  await expect(reveal).not.toBeAttached();
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
});

test("spoken output drives the actual playback analyser and can be interrupted", async ({ page }) => {
  test.setTimeout(90000);
  await workspace(page, true);
  const speechRequests: string[] = [];
  page.on("request", request => { if (request.url().endsWith("/speech")) speechRequests.push(request.url()); });
  await page.goto("/ai");
  await page.getByRole("textbox", { name: "Message Global Connects" }).fill("Give me a short spoken overview");
  await page.getByRole("button", { name: "Send message" }).click();
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByRole("button", { name: "Read reply aloud", exact: true })).toBeVisible();
  expect(speechRequests).toEqual([]);
  await page.getByRole("button", { name: "Read reply aloud", exact: true }).click();
  await expect(page.getByRole("button", { name: "Stop speaking" })).toBeVisible();
  await expect(page.locator("main[data-phase='speaking']")).toBeVisible();
  await expect.poll(() => page.getByTestId("assistant-voice-status").evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--voice-level")))).toBeGreaterThan(.1);
  await page.getByRole("button", { name: "Stop speaking" }).click();
  await expect(page.locator("main[data-phase='idle']")).toBeVisible();
});

test("denied administrator access keeps company information and uploads unavailable", async ({ page }) => {
  await assistantAuth(page);
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 403, json: { detail: "Administrator access required" } }));
  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "AI access is unavailable" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).not.toBeAttached();
  await expect(page.getByRole("button", { name: "Open library" })).not.toBeAttached();
});

test("anonymous visitors are sent to sign in before the private AI page mounts", async ({ page }) => {
  const refreshes: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/auth/refresh")) refreshes.push(request.url()); });
  await page.route("**/api/v1/ai-assistant/status", (route) => route.fulfill({ status: 401, json: { detail: "Authentication required" } }));
  await page.goto("/ai");
  await expect(page).toHaveURL(/(session-restore|login)/);
  await expect(page.getByRole("button", { name: "Start microphone" })).not.toBeAttached();
});

test("a failed answer is visible while the conversation panel stays collapsed", async ({ page }) => {
  await workspace(page);
  await page.route("**/api/v1/ai-assistant/chat", route => route.fulfill({ contentType:"text/event-stream", body:stream([{type:"error",code:"provider_configuration",message:"Check the AI provider connection."}]) }));
  await page.goto("/ai");
  await page.getByLabel("Message Global Connects",{exact:true}).fill("A synthetic question");
  await page.getByRole("button",{name:"Send message",exact:true}).click();
  await expect(page.getByRole("main",{name:"Global Connects AI workspace"}).getByRole("alert")).toContainText("Check the AI provider connection.");
  await expect(page.getByRole("main",{name:"Global Connects AI workspace"})).toHaveAttribute("data-conversation-open","false");
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
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
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

test("conversation slides away and restores its draft, focus, and centered composer on desktop and phone", async ({ page }, testInfo) => {
  await workspace(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/ai");
  const input = page.getByRole("textbox", { name: "Message Global Connects" });
  await input.fill("Check the current documents");
  await page.getByRole("button", { name: "Send message" }).click();
  const main = page.getByRole("main");
  const stage = page.getByTestId("assistant-stage");
  await expect(main).toHaveCSS("background-color", "rgb(0, 0, 0)");
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByRole("table")).toContainText("Synthetic departure");
  const aligned = async () => {
    const [visual, composer] = await Promise.all([stage.boundingBox(), input.boundingBox()]);
    return Math.abs(visual!.x + visual!.width / 2 - composer!.x - composer!.width / 2);
  };
  await expect.poll(aligned).toBeLessThan(2);
  await input.fill("Keep this draft while the conversation is hidden");
  await stage.evaluate(async (element) => {
    // Measure the open column after its actual CSS transition, independent of GPU speed.
    await Promise.all((element.parentElement?.parentElement?.getAnimations() ?? []).map((animation) => animation.finished));
  });
  const openWidth = (await stage.boundingBox())!.width;
  await page.screenshot({ path: testInfo.outputPath("ai-black-conversation-open.png") });
  await page.getByRole("button", { name: "Hide conversation" }).click();
  await expect(page.getByRole("button", { name: "Show conversation" })).toBeFocused();
  await expect(main).toHaveAttribute("data-conversation-open", "false");
  await expect(page.locator("#assistant-conversation-panel")).toHaveAttribute("inert", "");
  await expect.poll(async () => (await stage.boundingBox())!.width).toBeGreaterThan(openWidth + 250);
  await expect.poll(aligned).toBeLessThan(2);
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("ai-black-conversation-hidden.png") });
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Hide conversation" })).toBeFocused();
  await expect(input).toHaveValue("Keep this draft while the conversation is hidden");
  await expect.poll(aligned).toBeLessThan(2);
  await expect(page.getByRole("table")).toContainText("Synthetic departure");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(input).toBeInViewport();
  await expect.poll(aligned).toBeLessThan(2);
  await page.getByRole("button", { name: "Hide conversation" }).click();
  await expect(page.getByRole("button", { name: "Show conversation" })).toBeInViewport();
  await expect(input).toBeInViewport();
  await page.getByRole("button", { name: "Show conversation" }).click();
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).toBeVisible();
  await expect(input).toHaveValue("Keep this draft while the conversation is hidden");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ai-black-conversation-phone.png") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Hide conversation" }).click();
  await expect.poll(() => page.locator("#assistant-conversation-panel").evaluate((element) => parseFloat(getComputedStyle(element).transitionDuration))).toBeLessThan(.001);
});

test("saved voice conversations can be cancelled, retried and deleted without losing the draft or library", async ({ page }) => {
  await workspace(page);
  let exists = true, attempts = 0;
  await page.route("**/api/v1/ai-assistant/conversations", (route) => route.fulfill({ json: { items: exists ? [{ id: conversationId, title: "Voice conversation", created_at: timestamp }] : [], next_cursor: null } }));
  await page.route(`**/api/v1/ai-assistant/conversations/${conversationId}`, async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 503, json: { detail: { code: "deletion_incomplete", message: "Deletion could not finish. Please try again." } } });
    exists = false;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/ai");
  await page.getByRole("button", { name: "Open conversations" }).click();
  await page.getByRole("button", { name: /^Voice conversation/ }).click();
  await expect(page.getByText("What is pending?", { exact: true })).toBeVisible();
  const input = page.getByRole("textbox", { name: "Message Global Connects" });
  await input.fill("Retain my unsent draft");
  await page.getByRole("button", { name: "Open conversations" }).click();
  const remove = page.getByRole("button", { name: "Delete Voice conversation", exact: true });
  await remove.click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(attempts).toBe(0);
  await expect(remove).toBeFocused();
  await remove.click();
  await page.getByRole("button", { name: "Delete conversation", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("Deletion could not finish");
  await expect(remove).toBeVisible();
  await expect(input).toHaveValue("Retain my unsent draft");
  await page.getByRole("button", { name: "Delete conversation", exact: true }).click();
  await expect(remove).toHaveCount(0);
  await expect(page.getByText("Your saved conversations will appear here.")).toBeVisible();
  await expect(page.getByRole("button", { name: "New conversation", exact: true }).last()).toBeFocused();
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await expect(page.getByRole("region", { name: "Conversation", exact: true })).toHaveCount(0);
  await expect(input).toHaveValue("Retain my unsent draft");
  await page.reload();
  await page.getByRole("button", { name: "Open conversations" }).click();
  await expect(page.getByText("Your saved conversations will appear here.")).toBeVisible();
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page.getByRole("button", { name: "Open library" }).click();
  await expect(page.getByRole("button", { name: "View Travel inspiration 1" })).toBeVisible();
  expect(attempts).toBe(2);
});

test("the same sculpture particles respond to mouse and voice together, then to the mouse around an image", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await workspace(page);
  await syntheticMicrophone(page);
  await observeSculpture(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/ai");
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
  const quiet = await sculptureSignal(page);
  const stage = (await page.getByTestId("assistant-stage").boundingBox())!;
  await page.mouse.move(stage.x + stage.width * .5, stage.y + stage.height * .5, { steps: 8 });
  await expect.poll(async () => (await sculptureSignal(page)).pointer).toBeGreaterThan(.5);
  await expect(page.getByRole("button", { name: "Start microphone" })).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await page.evaluate(() => (window as unknown as { __voiceTest: { setVolume: (value: number) => void } }).__voiceTest.setVolume(.22));
  await page.mouse.move(stage.x + stage.width * .63, stage.y + stage.height * .45, { steps: 8 });
  await expect.poll(async () => (await sculptureSignal(page)).voice).toBeGreaterThan(.3);
  await expect.poll(async () => (await sculptureSignal(page)).pointer).toBeGreaterThan(.5);
  const combined = await sculptureSignal(page);
  expect(combined.particles).toBeGreaterThan(quiet.particles * 30);
  expect(combined.error).toBe(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Add files or create images" }).click();
  await page.getByRole("button", { name: /Create images.*Bring an idea/ }).click();
  await page.getByRole("textbox", { name: "Describe your image" }).fill("Create a synthetic travel preview");
  await page.getByRole("button", { name: "Create images", exact: true }).click();
  const reveal = page.getByTestId("image-reveal");
  await expect.poll(() => reveal.evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--reveal")))).toBe(1);
  const panel = (await page.locator("[data-image-panel]").boundingBox())!;
  await page.mouse.move(panel.x + panel.width + 14, panel.y + panel.height * .5, { steps: 12 });
  await expect.poll(async () => (await sculptureSignal(page)).pointer).toBeGreaterThan(.5);
  const boundary = await sculptureSignal(page);
  expect(boundary.particles).toBe(combined.particles);
  expect(boundary.error).toBe(0);
  await sculptureBoundary(page, true);
  await page.screenshot({ path: testInfo.outputPath("ai-image-fluid-boundary-pointer.png") });
  await page.mouse.move(5, 5);
  await expect.poll(async () => (await sculptureSignal(page)).pointer).toBeLessThan(.02);
  await page.getByRole("button", { name: "Close image", exact: true }).click();
  await expect(reveal).not.toBeAttached();
  await expect(page.getByTestId("voice-sculpture")).toHaveAttribute("data-renderer", "webgl");
});

test("the last chat restores for this account and device with the output collapsed", async ({ page }) => {
  await workspace(page);
  await page.goto("/ai");
  await page.getByRole("button", { name: "Open conversations", exact: true }).click();
  await page.getByRole("button", { name: /^A saved departure plan/ }).click();
  await expect(page.getByText("What is pending?", { exact: true })).toBeVisible();
  await page.reload();
  const tab=page.getByRole("button", { name: "Show conversation", exact: true });
  await expect(tab).toBeVisible();
  await expect(page.locator("#assistant-conversation-panel")).toHaveAttribute("inert", "");
  expect(await tab.locator("svg").count()).toBe(1);
  await expect(tab.locator("svg")).toHaveAttribute("width", "28");
  await tab.click();
  await expect(page.getByText("What is pending?", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New conversation", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Message Global Connects" })).toBeVisible();
  await expect(tab).not.toBeAttached();
  await expect(page.getByText("What is pending?", { exact: true })).not.toBeAttached();
});

test("original particles morph through logo, text, emoji and an audio-reactive face and return", async ({ page }, testInfo) => {
  test.setTimeout(180000);
  await workspace(page,true);
  await observeSculpture(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/ai");
  const sculpture=page.getByTestId("voice-sculpture");
  await expect(sculpture).toHaveAttribute("data-renderer", "webgl");
  const canvas=sculpture.locator("canvas").last();
  const [source,draw]=await Promise.all([sculpture.boundingBox(),canvas.boundingBox()]);
  expect(draw!.height).toBeGreaterThan(source!.height+130);
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  const dialog=page.getByRole("dialog", { name: "Sculpture appearance", exact: true });
  await dialog.getByRole("button", { name: "Company logo", exact: true }).click();
  await expect.poll(async()=>(await sculptureSignal(page)).morph).toBe(1);
  const count=(await sculptureSignal(page)).particles;
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("vrps-company-logo.png") });
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await dialog.getByRole("button", { name: "Text", exact: true }).click();
  await page.getByLabel("Your words", { exact: true }).fill("Hello, Global Connects");
  await dialog.getByRole("button", { name: "Form text", exact: true }).click();
  await expect(sculpture).toHaveAttribute("data-shape", "text");
  await expect.poll(async()=>(await sculptureSignal(page)).morphMix).toBe(1);
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("vrps-text.png") });
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await dialog.getByRole("button", { name: "Emoji", exact: true }).click();
  await dialog.getByRole("button", { name: "Heart", exact: true }).click();
  await expect.poll(async()=>(await sculptureSignal(page)).morphMix).toBe(1);
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("vrps-heart.png") });
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await dialog.getByRole("button", { name: "Talking face", exact: true }).click();
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await page.getByRole("textbox", { name: "Message Global Connects" }).fill("Give me a short overview");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await page.getByRole("button", { name: "Read reply aloud", exact: true }).click();
  await page.getByRole("button", { name: "Hide conversation", exact: true }).click();
  await expect.poll(async()=>(await sculptureSignal(page)).phase).toBeGreaterThan(2.8);
  await expect.poll(async()=>(await sculptureSignal(page)).voice).toBeGreaterThan(.2);
  const speaking=await sculptureSignal(page);
  expect(speaking.particles).toBe(count);expect(speaking.error).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("vrps-speaking-face.png") });
  await page.getByRole("button", { name: "Stop speaking", exact: true }).click();
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await dialog.getByRole("button", { name: "Sculpture", exact: true }).click();
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await expect.poll(async()=>(await sculptureSignal(page)).morph).toBe(0);
  await expect(sculpture).toHaveAttribute("data-renderer", "webgl");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Sculpture appearance", exact: true }).click();
  await dialog.getByRole("button", { name: "Emoji", exact: true }).click();
  await dialog.getByRole("button", { name: "Globe", exact: true }).click();
  await page.getByRole("button", { name: "Close sculpture appearance", exact: true }).click();
  await expect.poll(async()=>(await sculptureSignal(page)).morph).toBe(1);
  expect((await sculptureSignal(page)).stateMotion).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("vrps-mobile-globe-reduced-motion.png") });
});
