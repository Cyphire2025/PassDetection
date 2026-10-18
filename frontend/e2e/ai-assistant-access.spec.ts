import { expect, test, type Page } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";
import { DEFAULT_USAGE_LIMITS } from "../features/ai/settings-api";

const configuration = { enabled: true, allowed_roles: [], allowed_user_ids: [], provider: "gemini",
  gemini_model: "gemini-3.8-flash", gemini_live_model: "gemini-3.8-live", gemini_image_model: "gemini-3.1-flash-image",
  gemini_voice: "Zephyr", reasoning_effort: "high", openai_reasoning_effort: "high", openai_speech_model: "", openai_voice: "marin", usage_limits: DEFAULT_USAGE_LIMITS };

async function fixture(page: Page, role = "super_admin", allowed = true) {
  await assistantAuth(page, role);
  const state = { revision: 0, configuration: { ...configuration }, credentials: { gemini: false, openai: false }, granted_users: [] };
  const writes: Record<string, unknown>[] = [];
  await page.route("**/api/v1/ai-assistant/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: state.configuration.enabled, allowed: allowed && state.configuration.enabled } });
    if (path.endsWith("/status")) return route.fulfill({ json: { configured: true, speech_configured: true,
      provider: state.configuration.provider === "gemini" ? "gemini" : "openai", mode: state.configuration.provider, native_voice: state.configuration.provider !== "openai", voice_provider: state.configuration.provider === "openai" ? "openai" : "gemini", model: state.configuration.provider === "gemini" ? "gemini-3.8-flash" : "gpt-6-luna", reasoning_effort: state.configuration.openai_reasoning_effort,
      account_id: "synthetic", account_scope: role, settings_revision: state.revision, can_manage_settings: role === "super_admin", access: "read_only" } });
    if (path.endsWith("/live")) return route.fulfill({ json: { observed_at: new Date().toISOString(), agencies: [] } });
    if (path.endsWith("/people")) return route.fulfill({ json: { items: [], has_more: false } });
    if (path.endsWith("/settings/usage")) return route.fulfill({ json: { observed_at: new Date().toISOString(), resets_at: new Date(Date.now()+3600000).toISOString(), limits: state.configuration.usage_limits, used: { voice_chats: 2, typed_requests: 7, images: 1, uploads: 3, speech_requests: 4 } } });
    if (path.endsWith("/settings")) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON(); writes.push(body);
        state.configuration = body.configuration; state.revision++;
        if (body.gemini_api_key) state.credentials.gemini = true;
        if (body.openai_api_key) state.credentials.openai = true;
      }
      return route.fulfill({ json: state });
    }
    if (path.endsWith("/settings/check")) return route.fulfill({ json: { ok: true, message: "API key accepted." } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.route("**/api/v1/dashboard/stats", (route) => route.fulfill({ json: { total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [] } }));
  return { state, writes };
}

test("header orb opens and shrinks while retaining the dashboard and its microphone policy", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await fixture(page);
  await page.goto("/dashboard");
  const orb = page.getByRole("button", { name: "Open Global Connects AI", exact: true });
  await expect(orb).toBeVisible();
  await page.evaluate(() => { document.documentElement.dataset.aiNavigationProof = "same-document"; });
  const bounds = await orb.boundingBox();
  await orb.click();
  const overlay = page.getByTestId("assistant-overlay");
  await expect(overlay).toBeVisible();
  await expect(page.getByRole("main", { name: "Global Connects AI workspace" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.aiNavigationProof)).toBe("same-document");
  expect(await page.evaluate(() => (document as Document & { featurePolicy: { allowsFeature: (name: string) => boolean } }).featurePolicy.allowsFeature("microphone"))).toBe(true);
  await expect(overlay).toHaveCSS("clip-path", "none");
  await page.screenshot({ path: testInfo.outputPath("ai-expanded-from-header.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("link", { name: "AI settings", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole("button", { name: "Back to workspace" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(overlay).not.toBeAttached();
  await expect(orb).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.aiNavigationProof)).toBe("same-document");
  await expect(orb).toBeFocused();
  expect(bounds!.width).toBeGreaterThan(30);
});

test("superadmin can save a key and grants, then disable the launcher", async ({ page }) => {
  const { writes } = await fixture(page);
  await page.goto("/settings/ai");
  await expect(page.getByTestId("assistant-settings")).toBeVisible();
  const key = page.getByLabel("Gemini AI Studio API key", { exact: true });
  await key.fill("synthetic-browser-key-123456");
  await page.getByLabel("Managers", { exact: true }).check();
  await page.getByRole("button", { name: "Save AI settings", exact: true }).click();
  await expect(key).toHaveValue("");
  expect(writes[0].gemini_api_key).toBe("synthetic-browser-key-123456");
  expect((writes[0].configuration as typeof configuration).allowed_roles).toContain("agency_manager");
  await expect(page.getByRole("button", { name: "Open Global Connects AI", exact: true })).toBeVisible();
  await page.getByRole("switch", { name: "Enable Global Connects AI" }).uncheck();
  await page.getByRole("button", { name: "Save AI settings", exact: true }).click();
  await expect(page.getByRole("button", { name: "Open Global Connects AI", exact: true })).not.toBeAttached();
  expect(await page.evaluate(() => localStorage.getItem("synthetic-browser-key-123456"))).toBeNull();
});

test("ungranted staff cannot see the orb or manage settings", async ({ page }) => {
  await fixture(page, "agency_staff", false);
  await page.goto("/dashboard");
  // Staff's established landing route is All Groups rather than Dashboard.
  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Global Connects AI", exact: true })).not.toBeAttached();
  await page.goto("/settings/ai");
  await expect(page.getByLabel("Gemini AI Studio API key", { exact: true })).not.toBeAttached();
  await expect(page.getByTestId("assistant-settings")).not.toBeAttached();
});

test("combined mode saves both connections and the selected Luna reasoning on desktop and phone", async ({ page }, testInfo) => {
  const { state, writes } = await fixture(page);
  await page.goto("/settings/ai");
  await page.getByLabel("Provider mode", { exact: true }).selectOption("hybrid");
  await page.getByLabel("OpenAI API key", { exact: true }).fill("synthetic-browser-openai-123");
  await page.getByLabel("Gemini AI Studio API key", { exact: true }).fill("synthetic-browser-gemini-123");
  const reasoning = page.getByRole("combobox", { name: "Luna reasoning", exact: true });
  await expect(reasoning.locator("option")).toHaveCount(6);
  await reasoning.selectOption("low");
  await page.getByRole("button", { name: "Save AI settings", exact: true }).click();
  await expect(page.getByText("AI settings saved.", { exact: true })).toBeVisible();
  expect(writes[0].openai_api_key).toBe("synthetic-browser-openai-123");
  expect(writes[0].gemini_api_key).toBe("synthetic-browser-gemini-123");
  expect(state.configuration.openai_reasoning_effort).toBe("low");
  expect(state.configuration.provider).toBe("hybrid");
  await page.reload();
  await expect(reasoning).toHaveValue("low");
  await expect(page.getByLabel("Provider mode", { exact: true })).toHaveValue("hybrid");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("hybrid-settings-mobile.png"), fullPage: true });
});

test("combined voice saves captions before Luna continues in the same chat", async ({ page }) => {
  test.setTimeout(90000);
  const { state } = await fixture(page); state.configuration.provider = "hybrid";
  await syntheticMicrophone(page);
  let typed = 0, conversation = "", voiceSaved = false, rejectSave = false;
  const starts: string[] = [], ends: string[] = [], transcribes: string[] = [];
  page.on("request", request => { if (request.url().endsWith("/transcribe")) transcribes.push(request.url()); });
  await page.route("**/api/v1/ai-assistant/chat", route => {
    const body = route.request().postDataJSON();
    if (!typed) conversation = body.conversation_id;
    else { expect(voiceSaved).toBe(true); expect(body.conversation_id).toBe(conversation); }
    typed++;
    return route.fulfill({ contentType:"text/event-stream", body: 'data: '+JSON.stringify({type:"text_delta",text:"Luna's typed reply "+typed})+'\n\ndata: '+JSON.stringify({type:"done",request_id:body.request_id})+'\n\n' });
  });
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", socket => {
    let emitted = false;
    socket.onMessage(raw => {
      const message = JSON.parse(String(raw));
      if (message.type === "start") { starts.push(message.conversation_id); socket.send(JSON.stringify({type:"ready",conversation_id:message.conversation_id,max_session_seconds:600})); }
      if (message.type === "audio" && !emitted) {
        emitted = true; socket.send(JSON.stringify({type:"input_transcript",text:"My spoken question.",turn_id:"hybrid-voice-turn"}));
        socket.send(JSON.stringify({type:"text_delta",text:"Gemini's spoken reply.",turn_id:"hybrid-voice-turn"}));
      }
      if (message.type === "end") {
        if (rejectSave) { socket.close({code:1000,reason:"Save unavailable"}); return; }
        ends.push(message.type); voiceSaved = true;
        socket.send(JSON.stringify({type:"turn_complete",turn_id:"hybrid-voice-turn",turn:{id:"hybrid-voice-turn",user:"My spoken question.",assistant:"Gemini's spoken reply.",created_at:"2026-10-19T00:00:00Z"}}));
        socket.send(JSON.stringify({type:"voice_saved",conversation_id:conversation})); socket.close({code:1000,reason:"Saved"});
      }
    });
  });
  await page.goto("/ai");
  await page.getByLabel("Message Global Connects", {exact:true}).fill("My typed question.");
  await page.getByRole("button",{name:"Send message",exact:true}).click();
  await expect.poll(() => typed).toBe(1);
  await page.getByRole("button",{name:"Start microphone",exact:true}).click();
  await expect(page.getByRole("button",{name:"End voice conversation",exact:true})).toBeVisible();
  await expect.poll(() => starts.length).toBe(1);
  expect(starts[0]).toBe(conversation);
  await page.getByLabel("Message Global Connects",{exact:true}).fill("Continue after my voice answer.");
  await page.getByRole("button",{name:"Send message",exact:true}).click();
  await expect.poll(() => typed).toBe(2);
  expect(ends).toEqual(["end"]); expect(transcribes).toEqual([]);
  await page.getByRole("button",{name:"Show conversation",exact:true}).click();
  await expect(page.getByText("My spoken question.",{exact:true})).toBeVisible();
  await expect(page.getByText("Gemini's spoken reply.",{exact:true})).toBeVisible();
  await expect(page.getByText("Luna's typed reply 2",{exact:true})).toBeVisible();
  rejectSave = true;
  await page.getByRole("button",{name:"Start microphone",exact:true}).click();
  await expect(page.getByRole("button",{name:"End voice conversation",exact:true})).toBeVisible();
  await page.getByLabel("Message Global Connects",{exact:true}).fill("Keep this draft if saving fails.");
  await page.getByRole("button",{name:"Send message",exact:true}).click();
  await expect(page.getByRole("main",{name:"Global Connects AI workspace"}).getByRole("alert")).toContainText("Your typed draft is still here");
  await expect(page.getByLabel("Message Global Connects",{exact:true})).toHaveValue("Keep this draft if saving fails.");
  expect(typed).toBe(2);
});

test("superadmin can edit allowances, inspect current usage and retain limits after reload", async ({ page }, testInfo) => {
  const { writes } = await fixture(page);
  await page.goto("/settings/ai");
  const limits = page.getByRole("region", { name: "Usage limits" });
  await expect(limits).toBeVisible();
  await expect(page.getByTestId("usage-voice_chats")).toHaveText("2 / 30");
  await expect(limits).toContainText("Daily reset:");
  await page.getByLabel("Voice chats per day", { exact: true }).fill("120");
  await page.getByLabel("Maximum voice connection (minutes)", { exact: true }).fill("61");
  await expect(page.getByRole("button", { name: "Save AI settings", exact: true })).toBeDisabled();
  await page.getByLabel("Maximum voice connection (minutes)", { exact: true }).fill("25");
  await page.getByLabel("Typed requests per day", { exact: true }).fill("500");
  await page.getByLabel("Images per day", { exact: true }).fill("30");
  await page.getByLabel("File uploads per day", { exact: true }).fill("150");
  await page.getByLabel("Speech requests per day", { exact: true }).fill("600");
  await page.getByRole("button", { name: "Save AI settings", exact: true }).click();
  await expect(page.getByTestId("usage-voice_chats")).toHaveText("2 / 120");
  expect((writes[0].configuration as typeof configuration).usage_limits.voice_connection_minutes).toBe(25);
  await page.reload();
  await expect(page.getByLabel("Voice chats per day", { exact: true })).toHaveValue("120");
  await expect(page.getByTestId("usage-typed_requests")).toHaveText("7 / 500");
  await page.setViewportSize({ width: 390, height: 844 });
  await limits.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ai-usage-settings-mobile.png"), fullPage: true });
});

test("native voice sends PCM without transcribe requests, plays audio, and releases input", async ({ page }) => {
  test.setTimeout(90000);
  await fixture(page);
  await syntheticMicrophone(page);
  const transcribes: string[] = []; let packets = 0;
  page.on("request", (request) => { if (request.url().endsWith("/transcribe")) transcribes.push(request.url()); });
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    socket.onMessage((raw) => {
      const value = JSON.parse(String(raw));
      if (value.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: value.conversation_id, max_session_seconds: 600 }));
      if (value.type !== "audio") return;
      packets++;
      if (packets !== 3) return;
      const pcm = Buffer.alloc(24000 * 2 * 2);
      for (let sample = 0; sample < pcm.length / 2; sample++) pcm.writeInt16LE(Math.round(Math.sin(sample * Math.PI * 2 * 180 / 24000) * 14000), sample * 2);
      socket.send(JSON.stringify({ type: "input_transcript", text: "What is pending?", turn_id: "voice-turn" }));
      socket.send(JSON.stringify({ type: "text_delta", text: "There are three pending documents.", turn_id: "voice-turn" }));
      socket.send(JSON.stringify({ type: "audio", data: pcm.toString("base64"), sample_rate: 24000, turn_id: "voice-turn" }));
    });
  });
  await page.goto("/ai");
  await page.getByTestId("assistant-voice-status").evaluate((element) => {
    // Observe the actual rendered level throughout the short audio reply. A
    // caption assertion may resolve after playback has already finished.
    const probe = window as unknown as { __nativePlaybackPeak: number };
    probe.__nativePlaybackPeak = 0;
    new MutationObserver(() => {
      probe.__nativePlaybackPeak = Math.max(probe.__nativePlaybackPeak, Number((element as HTMLElement).style.getPropertyValue("--voice-level")));
    }).observe(element, { attributes: true, attributeFilter: ["style"] });
  });
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByRole("button", { name: "End voice conversation" })).toBeVisible();
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByText("There are three pending documents.", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __nativePlaybackPeak: number }).__nativePlaybackPeak)).toBeGreaterThan(.1);
  await page.getByRole("button", { name: "End voice conversation" }).click();
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
  expect(packets).toBeGreaterThan(1);
  expect(transcribes).toEqual([]);
});

test("voice lookup recovery replaces a partial reply, pauses input, then resumes with sources and speech", async ({ page }) => {
  test.setTimeout(90000);
  await fixture(page);
  await syntheticMicrophone(page);
  let packets = 0;
  const textInputs: string[] = [];
  let reset: () => void = () => { throw new Error("Synthetic socket is not ready"); };
  let complete: () => void = () => { throw new Error("Synthetic socket is not ready"); };
  await page.routeWebSocket("**/api/v1/ai-assistant/voice", (socket) => {
    reset = () => socket.send(JSON.stringify({ type: "answer_reset", turn_id: "recovery-turn" }));
    complete = () => {
      const pcm = Buffer.alloc(24000 * 2 * 2);
      for (let sample = 0; sample < pcm.length / 2; sample++) pcm.writeInt16LE(Math.round(Math.sin(sample * Math.PI * 2 * 180 / 24000) * 14000), sample * 2);
      const source = { view: "passport_details", observed_at: "2026-10-18T00:00:00Z", completeness: "complete" };
      socket.send(JSON.stringify({ type: "source", source, turn_id: "recovery-turn" }));
      socket.send(JSON.stringify({ type: "text_delta", text: "Ada's saved email is ada@example.test.", turn_id: "recovery-turn" }));
      socket.send(JSON.stringify({ type: "audio", data: pcm.toString("base64"), sample_rate: 24000, turn_id: "recovery-turn" }));
      socket.send(JSON.stringify({ type: "turn_complete", turn_id: "recovery-turn", turn: { id: "recovery-turn", user: "Find Ada's saved contact", assistant: "Ada's saved email is ada@example.test.", created_at: "2026-10-18T00:00:00Z", sources: [source], images: [] } }));
    };
    socket.onMessage((raw) => {
      const value = JSON.parse(String(raw));
      if (value.type === "start") socket.send(JSON.stringify({ type: "ready", conversation_id: value.conversation_id, max_session_seconds: 600 }));
      if (value.type === "text") textInputs.push(value.text);
      if (value.type !== "audio" || ++packets !== 3) return;
      socket.send(JSON.stringify({ type: "input_transcript", text: "Find Ada's saved contact", turn_id: "recovery-turn" }));
      socket.send(JSON.stringify({ type: "text_delta", text: "An incomplete voice reply.", turn_id: "recovery-turn" }));
    });
  });
  await page.goto("/ai");
  await page.getByRole("button", { name: "Start microphone" }).click();
  await page.getByRole("button", { name: "Show conversation", exact: true }).click();
  await expect(page.getByText("An incomplete voice reply.", { exact: true })).toBeVisible();
  reset();
  await expect(page.getByRole("button", { name: "Stop response" })).toBeVisible();
  await expect(page.getByText("An incomplete voice reply.", { exact: true })).not.toBeAttached();
  const draft = page.getByRole("textbox", { name: "Message Global Connects" });
  await draft.fill("Keep this draft while checking");
  await draft.press("Enter");
  await expect(draft).toHaveValue("Keep this draft while checking");
  const pausedAt = packets;
  await page.waitForTimeout(350); // Allow any capture packet already in flight to drain.
  expect(packets).toBeLessThanOrEqual(pausedAt + 1);
  expect(textInputs).toEqual([]);
  complete();
  await expect(page.getByText("Ada's saved email is ada@example.test.", { exact: true })).toBeVisible();
  await expect(page.getByText("passport details", { exact: true })).toBeVisible();
  await expect.poll(() => packets).toBeGreaterThan(pausedAt + 1);
  await page.getByRole("button", { name: "End voice conversation" }).click();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
});
