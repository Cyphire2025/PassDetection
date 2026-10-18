import { expect, test, type Page } from "@playwright/test";
import { assistantAuth } from "./support/assistant-auth";
import { syntheticMicrophone } from "./support/ai-voice-fixtures";

const configuration = { enabled: true, allowed_roles: [], allowed_user_ids: [], provider: "gemini",
  gemini_model: "gemini-3.8-flash", gemini_live_model: "gemini-3.8-live", gemini_image_model: "gemini-3.1-flash-image",
  gemini_voice: "Zephyr", reasoning_effort: "high", openai_speech_model: "", openai_voice: "marin" };

async function fixture(page: Page, role = "super_admin", allowed = true) {
  await assistantAuth(page, role);
  const state = { revision: 0, configuration: { ...configuration }, credentials: { gemini: false, openai: false }, granted_users: [] };
  const writes: Record<string, unknown>[] = [];
  await page.route("**/api/v1/ai-assistant/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/availability")) return route.fulfill({ json: { enabled: state.configuration.enabled, allowed: allowed && state.configuration.enabled } });
    if (path.endsWith("/status")) return route.fulfill({ json: { configured: true, speech_configured: true,
      provider: "gemini", native_voice: true, model: "gemini-3.8-flash", reasoning_effort: "high",
      account_id: "synthetic", account_scope: role, settings_revision: state.revision, can_manage_settings: role === "super_admin", access: "read_only" } });
    if (path.endsWith("/live")) return route.fulfill({ json: { observed_at: new Date().toISOString(), agencies: [] } });
    if (path.endsWith("/people")) return route.fulfill({ json: { items: [], has_more: false } });
    if (path.endsWith("/settings")) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON(); writes.push(body);
        state.configuration = body.configuration; state.revision++;
        if (body.gemini_api_key) state.credentials.gemini = true;
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
  await expect(page.getByText("There are three pending documents.", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __nativePlaybackPeak: number }).__nativePlaybackPeak)).toBeGreaterThan(.1);
  await page.getByRole("button", { name: "End voice conversation" }).click();
  await expect(page.getByRole("button", { name: "Start microphone" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { tracksStopped: () => boolean } }).__voiceTest.tracksStopped())).toBe(true);
  expect(packets).toBeGreaterThan(1);
  expect(transcribes).toEqual([]);
});
