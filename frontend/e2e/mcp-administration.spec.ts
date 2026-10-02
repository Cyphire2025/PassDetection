import { expect, test, type Page, type Route } from "@playwright/test";

const resource = "https://app.example.test/mcp";
const callback = "http://127.0.0.1:49153/callback";
const oauth = { client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: callback, resource,
  state: "opaque state & symbols / = unicode ✓", code_challenge: "x".repeat(43), code_challenge_method: "S256", response_type: "code", scope: "mcp:read mcp:export" };

async function setup(page: Page, role = "super_admin", requireStepUp = false) {
  const errors: string[] = [];
  const requests: Array<{ method: string; path: string; body: unknown }> = [];
  let enabled = true;
  let verified = !requireStepUp;
  const verifications: unknown[] = [];
  let grant = { id: "grant-a", user_id: "mcp-test-admin", client_id: oauth.client_id, name: "Office desktop", capabilities: ["mcp:read", "mcp:export"],
    device_platform: "Windows", enabled: true, created_at: "2026-09-29T00:00:00Z", expires_at: "2099-10-06T00:00:00Z", last_used_at: "2026-09-29T12:00:00Z", revoked_at: null as string | null, status: "active" };
  const connectionRequests = [
    { id: "00000000-0000-4000-8000-000000000011", name: "New Codex connection", client_name: "Codex", device_platform: "macOS", comparison_code: "ABCD-1234", requested_capabilities: ["mcp:read"], status: "pending", created_at: "2026-10-02T12:00:00Z", expires_at: "2099-10-02T12:10:00Z", decided_at: null as string | null },
    { id: "00000000-0000-4000-8000-000000000012", name: "Unknown connection", client_name: "Codex", device_platform: "Other", comparison_code: "EFGH-5678", requested_capabilities: ["mcp:read"], status: "pending", created_at: "2026-10-02T12:00:00Z", expires_at: "2099-10-02T12:10:00Z", decided_at: null as string | null },
  ];
  const mac = { ...grant, id: "grant-b", user_id: "other-admin", name: "My MacBook", device_platform: "macOS" };
  const user = { id: "mcp-test-admin", email: "mcp@example.test", full_name: "MCP Test Administrator", role, agency_id: null, is_active: true,
    last_login_at: null, created_at: "2026-09-29T00:00:00Z", updated_at: "2026-09-29T00:00:00Z", capabilities: role === "super_admin" ? ["mcp.manage"] : [] };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "isolated-mcp-fixture", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/auth/mfa/step-up" && method === "POST") {
      verifications.push(request.postDataJSON());
      verified = true;
      return json(route, { verified: true });
    }
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/admin/mcp")) {
      requests.push({ method, path, body: request.postData() ? request.postDataJSON() : null });
      if (role !== "super_admin") return json(route, { detail: "Superadmin required" }, 403);
      if (!verified && method !== "GET") return json(route, { error: { code: "STEP_UP_REQUIRED", message: "Confirm your identity before changing MCP access." } }, 403);
      if (path === "/api/v1/admin/mcp") return json(route, { read_only_mode: false, enabled, deployment_enabled: true, emergency_disabled: !enabled, resource,
        capabilities: ["mcp:read", "mcp:export", "mcp:upload", "mcp:change", "mcp:communicate", "mcp:diagnose"],
        approved_clients: {}, direct_clients: { [oauth.client_id]: ["http://127.0.0.1/callback"], "https://chatgpt.com/oauth/client.json": ["https://chatgpt.com/connector_platform_oauth_redirect"] },
        client_names: { [oauth.client_id]: "Codex", "https://chatgpt.com/oauth/client.json": "ChatGPT" }, environment: "qualification", revision: "fixture-revision", observed_at: "2026-09-29T12:00:00Z", qualification: "in_progress" });
      if (path.endsWith("/connection-requests")) return json(route, { items: connectionRequests, next_offset: null });
      if (/\/connection-requests\/[^/]+\/(approve|reject)$/.test(path) && method === "POST") {
        const item = connectionRequests.find((item) => path.includes(item.id))!;
        const body = request.postDataJSON();
        Object.assign(item, body, { status: path.endsWith("/approve") ? "approved" : "rejected", decided_at: "2026-10-02T12:03:00Z" });
        return json(route, item);
      }
      if (path.endsWith("/connections")) return json(route, { items: [grant, mac], next_offset: null });
      if (path.endsWith("/activity")) return json(route, { items: [{ id: "audit-a", action: "mcp.authorized", result: "success", entity_id: "grant-a", created_at: "2026-09-29T00:00:00Z" }], next_offset: null });
      if (path.endsWith("/operations")) return json(route, { items: [
        { id: "operation-a", operation: "confirm_whatsapp_message", status: "unknown", progress: 1, stage: "dispatch_cancelled_unknown",
          workflow_id: "00000000-0000-4000-8000-000000000123", connection_id: "00000000-0000-4000-8000-000000000456", revision: 4,
          created_entities: [{ entity_type: "client_group", entity_id: "group-a", path: "/passports/groups/00000000-0000-4000-8000-000000000001" }],
          created_at: "2026-09-29T11:00:00Z", updated_at: "2026-09-29T12:00:00Z", completed_at: null },
        { id: "operation-b", operation: "confirm_gc_push", status: "succeeded", progress: 1, stage: "dispatch_complete",
          workflow_id: "00000000-0000-4000-8000-000000000124", connection_id: "00000000-0000-4000-8000-000000000456", revision: 2,
          created_entities: [], created_at: "2026-09-29T11:00:00Z", updated_at: "2026-09-29T12:00:00Z", completed_at: "2026-09-29T12:00:00Z" },
        { id: "operation-c", operation: "confirm_whatsapp_reminder", status: "failed", progress: 1, stage: "dispatch_cancelled",
          workflow_id: "00000000-0000-4000-8000-000000000125", connection_id: "00000000-0000-4000-8000-000000000456", revision: 3,
          created_entities: [], created_at: "2026-09-29T11:00:00Z", updated_at: "2026-09-29T12:00:00Z", completed_at: "2026-09-29T12:00:00Z" },
      ], next_offset: null });
      if (path.endsWith("/artifacts")) return json(route, { items: [
        { id: "artifact-a", filename: "Passengers.xlsx", direction: "export", byte_size: 1024, status: "available", expires_at: "2026-09-29T13:00:00Z" },
        { id: "media-ready", filename: "Header.png", kind: "whatsapp_header", direction: "upload", byte_size: 256, status: "ready", expires_at: "2026-09-29T13:00:00Z" },
        { id: "media-unknown", filename: "Uncertain.png", kind: "whatsapp_header", direction: "upload", byte_size: 512, status: "unknown", expires_at: "2026-09-29T13:00:00Z" },
        { id: "contacts", filename: "Contacts.xlsx", kind: "contact_workbook", direction: "upload", byte_size: 800, status: "imported", expires_at: "2026-09-29T13:00:00Z" },
        { id: "source-pdf", filename: "Documents.pdf", kind: "artifact", direction: "upload", byte_size: 950, status: "ingested", expires_at: "2026-09-29T13:00:00Z" },
      ], next_offset: null });
      if (path.endsWith("/inventory")) return json(route, { tool_count: 7, environment: "qualification", qualification: "in_progress", tools: [
        ...["list_groups", "list_group_passports", "inspect_excel_export_options"].map((name) => ({ name, description: "Look up saved information.", capability: "mcp:read", read_only: true, deployment_available: true })),
        ...["inspect_excel_export", "prepare_excel_export", "resume_excel_export"].map((name) => ({ name, description: "Prepare a passport report.", capability: "mcp:export", read_only: false, deployment_available: true })),
        { name: "create_group", description: "Create a group.", capability: "mcp:change", read_only: false, deployment_available: false },
      ], file_transports: [{ name: "download_prepared_artifact", capability: "mcp:export" }, { name: "acknowledge_verified_delivery", capability: "mcp:export" }, { name: "upload_pdf", capability: "mcp:upload" }, { name: "prepare_whatsapp_header_image", capability: "mcp:upload", required_capabilities: ["mcp:upload", "mcp:communicate"] }] });
      if (path.endsWith("/control") && method === "PUT") { enabled = request.postDataJSON().enabled; return json(route, { enabled }); }
      if (path.endsWith("/grant-a/access") && method === "PATCH") { const allowed = request.postDataJSON().enabled; grant = { ...grant, enabled: allowed, status: allowed ? "active" : "disabled" }; return json(route, grant); }
      if (path.endsWith("/revoke") && method === "POST") { grant = { ...grant, status: "revoked", revoked_at: "2026-09-29T12:00:00Z" }; return json(route, { revoked: true }); }
      if (path.endsWith("/grant-a") && method === "PATCH") { grant = { ...grant, ...request.postDataJSON() }; return json(route, grant); }
      if (path.endsWith("/authorize") && method === "POST") return json(route, { redirect_url: `${callback}?${new URLSearchParams({ code: "fixture-one-use-code", state: request.postDataJSON().state, iss: new URL(resource).origin })}` });
      return json(route, { detail: "Unsupported MCP fixture request" }, 400);
    }
    if (method === "GET") return json(route, []);
    return json(route, { detail: "Unexpected mutation outside MCP fixture" }, 400);
  });
  return { errors, requests, verifications };
}

for (const width of [1440, 650, 390]) {
  test(`four MCP pages and independent device controls at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/admin/mcp");
    await expect(page.getByRole("heading", { name: "MCP access", exact: true })).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "MCP pages" });
    await expect(navigation.getByRole("link")).toHaveCount(4);
    await expect(page.getByText("Try a read in Codex", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Advanced", exact: true })).toHaveCount(0);
    const devices = page.getByRole("region", { name: "MCP devices" });
    const windows = devices.getByRole("article", { name: "Office desktop" });
    const mac = devices.getByRole("article", { name: "My MacBook" });
    await windows.getByRole("button", { name: "Disable", exact: true }).click();
    await expect(windows.getByRole("button", { name: "Enable", exact: true })).toBeEnabled();
    await expect(mac.getByRole("button", { name: "Disable", exact: true })).toBeEnabled();
    await windows.getByRole("button", { name: "Enable", exact: true }).click();
    await expect(windows.getByRole("button", { name: "Disable", exact: true })).toBeEnabled();
    for (const [label, path] of [["Devices", ""], ["Requests", "/requests"], ["Settings", "/settings"], ["Connection setup", "/setup"]]) {
      await navigation.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/admin/mcp${path}$`));
      await expect(page.getByRole("heading", { name: label, exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      const screenshot = testInfo.outputPath(`mcp-${label.replaceAll(" ", "-")}-${width}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      await testInfo.attach(`${label} ${width}px`, { path: screenshot, contentType: "image/png" });
    }
    const direct = page.getByRole("region", { name: "Direct MCP setup", exact: true });
    await expect(direct).toContainText("Streamable HTTP");
    await expect(direct).toContainText(resource);
    await expect(direct).toContainText("administrator");
    expect(state.requests.filter((item) => item.path.endsWith("/access"))).toHaveLength(2);
    expect(state.errors).toEqual([]);
  });
}

test("admin approves matching request and rejects another without issuing credentials in the dashboard", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/admin/mcp/requests");
  const pending = page.getByRole("article", { name: "New Codex connection" });
  await expect(pending).toContainText("ABCD-1234");
  await pending.getByRole("button", { name: "Approve", exact: true }).click();
  await pending.getByRole("textbox", { name: "Device name" }).fill("Yogesh MacBook");
  await pending.getByRole("button", { name: "Approve connection", exact: true }).click();
  await expect(page.getByRole("region", { name: "Recent request decisions" })).toContainText("Yogesh MacBook");
  await page.getByRole("article", { name: "Unknown connection" }).getByRole("button", { name: "Reject", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reject request", exact: true }).click();
  await expect(page.getByText("No pending requests", { exact: true })).toBeVisible();
  expect(state.requests.filter((item) => item.method === "POST").map((item) => item.path)).toEqual([
    "/api/v1/admin/mcp/connection-requests/00000000-0000-4000-8000-000000000011/approve",
    "/api/v1/admin/mcp/connection-requests/00000000-0000-4000-8000-000000000012/reject",
  ]);
  expect(state.errors).toEqual([]);
});

for (const cancel of [false, true]) {
  test(`global pause uses MFA and ${cancel ? "cancel preserves access" : "resume remains possible"}`, async ({ page }) => {
    const state = await setup(page, "super_admin", true);
    await page.goto("/admin/mcp/settings");
    const toggle = page.getByRole("switch", { name: "Allow MCP access", exact: true });
    await toggle.click();
    await page.getByRole("dialog").getByRole("button", { name: "Pause access", exact: true }).click();
    const identity = page.getByRole("dialog", { name: "Confirm this sensitive action" });
    await expect(identity).toBeVisible();
    if (cancel) {
      await identity.getByRole("button", { name: "Cancel identity confirmation" }).click();
      await expect(toggle).toBeChecked();
      expect(state.requests.filter((item) => item.method === "PUT")).toHaveLength(1);
    } else {
      await identity.getByRole("textbox", { name: "Verification code" }).fill("123456");
      await identity.getByRole("button", { name: "Verify and continue" }).click();
      await expect(toggle).not.toBeChecked();
      await expect(toggle).toBeEnabled();
      await toggle.click();
      await page.getByRole("dialog").getByRole("button", { name: "Resume access", exact: true }).click();
      await expect(toggle).toBeChecked();
      expect(state.verifications).toEqual([{ code: "123456" }]);
      expect(state.requests.filter((item) => item.method === "PUT")).toHaveLength(3);
    }
    expect(state.errors).toEqual([]);
  });
}

test("non-superadmin cannot open requests or load MCP administration data", async ({ page }) => {
  const state = await setup(page, "agency_staff");
  await page.goto("/admin/mcp/requests");
  await expect.poll(async () => new URL(page.url()).pathname === "/passports"
    || await page.getByRole("heading", { name: "This workspace is not available to your current role" }).isVisible()).toBe(true);
  expect(state.requests).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`anonymous request waits without login and returns approved OAuth callback at ${width}px`, async ({ page }, testInfo) => {
    const id = "00000000-0000-4000-8000-000000000011";
    let approved = false;
    const requests: { path: string; method: string; header?: string }[] = [];
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/auth/**", () => { throw new Error("Requester must not log in"); });
    await page.route("**/oauth/mcp/requests/**", async (route) => {
      const request = route.request();
      requests.push({ path: new URL(request.url()).pathname, method: request.method(), header: request.headers()["x-mcp-request"] });
      const body = request.method() === "POST" ? {
        redirect_url: `${callback}?${new URLSearchParams({ code: "one-use-code", state: oauth.state, iss: new URL(resource).origin })}`,
        client_id: oauth.client_id, redirect_uri: callback, resource, state: oauth.state,
      } : { id, name: "New Codex connection", client_name: "Codex", device_platform: "macOS", comparison_code: "ABCD-1234",
        requested_capabilities: ["mcp:read"], status: approved ? "approved" : "pending", created_at: "2026-10-02T12:00:00Z", expires_at: "2099-10-02T12:10:00Z" };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.route(`${callback}?**`, (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Connection received by client</h1>" }));
    await page.goto(`/mcp/connect?request_id=${id}`);
    await expect(page.getByRole("heading", { name: "Waiting for administrator approval" })).toBeVisible();
    await expect(page.getByText("ABCD-1234", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: /Password|Email/ })).toHaveCount(0);
    expect(requests.filter((item) => item.method === "POST")).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    const screenshot = testInfo.outputPath(`mcp-public-waiting-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`Public waiting ${width}px`, { path: screenshot, contentType: "image/png" });
    approved = true;
    await expect(page.getByRole("heading", { name: "Connection received by client" })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("state")).toBe(oauth.state);
    expect(requests.filter((item) => item.method === "POST")).toHaveLength(1);
    expect(requests.every((item) => item.header === id)).toBe(true);
  });
}
