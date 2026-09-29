import { expect, test, type Page, type Route } from "@playwright/test";

const resource = "https://app.example.test/mcp";
const callback = "http://127.0.0.1:8765/callback";
const oauth = { client_id: "global-connects-desktop", redirect_uri: callback, resource,
  state: "opaque state & symbols / = unicode ✓", code_challenge: "x".repeat(43), code_challenge_method: "S256", response_type: "code", scope: "mcp:read mcp:export" };

async function setup(page: Page, role = "super_admin") {
  const errors: string[] = [];
  const requests: Array<{ method: string; path: string; body: unknown }> = [];
  let enabled = true;
  let grant = { id: "grant-a", user_id: "mcp-test-admin", client_id: oauth.client_id, name: "Office desktop", capabilities: ["mcp:read", "mcp:export"],
    created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z", last_used_at: "2026-09-29T12:00:00Z", revoked_at: null as string | null, status: "active" };
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
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path.startsWith("/api/v1/admin/mcp")) {
      requests.push({ method, path, body: request.postData() ? request.postDataJSON() : null });
      if (role !== "super_admin") return json(route, { detail: "Superadmin required" }, 403);
      if (path === "/api/v1/admin/mcp") return json(route, { enabled, deployment_enabled: true, emergency_disabled: !enabled, resource,
        capabilities: ["mcp:read", "mcp:export", "mcp:upload", "mcp:change", "mcp:communicate", "mcp:diagnose"],
        approved_clients: { [oauth.client_id]: [callback] }, environment: "qualification", revision: "fixture-revision", observed_at: "2026-09-29T12:00:00Z", qualification: "in_progress" });
      if (path.endsWith("/connections")) return json(route, { items: [grant], next_offset: null });
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
      if (path.endsWith("/inventory")) return json(route, { tool_count: 2, environment: "qualification", qualification: "in_progress", tools: [
        { name: "list_groups", description: "Find groups.", capability: "mcp:read", read_only: true, deployment_available: true },
        { name: "create_group", description: "Create a group.", capability: "mcp:change", read_only: false, deployment_available: false },
      ], file_transports: [{ name: "upload_pdf", capability: "mcp:upload" }, { name: "prepare_whatsapp_header_image", capability: "mcp:upload", required_capabilities: ["mcp:upload", "mcp:communicate"] }] });
      if (path.endsWith("/control") && method === "PUT") { enabled = request.postDataJSON().enabled; return json(route, { enabled }); }
      if (path.endsWith("/revoke") && method === "POST") { grant = { ...grant, status: "revoked", revoked_at: "2026-09-29T12:00:00Z" }; return json(route, { revoked: true }); }
      if (path.endsWith("/grant-a") && method === "PATCH") { grant = { ...grant, ...request.postDataJSON() }; return json(route, grant); }
      if (path.endsWith("/authorize") && method === "POST") return json(route, { redirect_url: `${callback}?${new URLSearchParams({ code: "fixture-one-use-code", state: request.postDataJSON().state })}` });
      return json(route, { detail: "Unsupported MCP fixture request" }, 400);
    }
    if (method === "GET") return json(route, []);
    return json(route, { detail: "Unexpected mutation outside MCP fixture" }, 400);
  });
  return { errors, requests };
}

for (const width of [1440, 768, 390]) {
  test(`superadmin reviews, narrows, disables and revokes MCP at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/admin/mcp");
    await expect(page.getByRole("heading", { name: "MCP", exact: true })).toBeVisible();
    await expect(page.getByRole("article", { name: "Office desktop" })).toBeVisible();
    await expect(page.getByText(/Release qualification is in progress/)).toBeVisible();
    const screenshot = testInfo.outputPath(`mcp-connections-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`MCP connections ${width}px`, { path: screenshot, contentType: "image/png" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    await page.getByRole("button", { name: "Edit access" }).click();
    await page.getByRole("textbox", { name: "Connection name" }).fill("Travel laptop");
    await page.getByRole("checkbox", { name: /Exports/ }).uncheck();
    await expect(page.getByRole("checkbox", { name: /Communications/ })).toHaveCount(0);
    await page.getByRole("button", { name: "Save access" }).click();
    await expect(page.getByRole("article", { name: "Travel laptop" })).toBeVisible();
    await page.getByRole("button", { name: "Disable MCP access" }).click();
    await expect(page.getByRole("button", { name: "Enable MCP access" })).toBeVisible();
    await page.getByRole("button", { name: "Revoke", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Revoke connection" }).click();
    await expect(page.getByRole("article", { name: "Travel laptop" })).toContainText("revoked");
    await page.getByRole("button", { name: "Activity", exact: true }).click();
    await expect(page.getByText("mcp.authorized", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Workflows", exact: true }).click();
    await expect(page.getByText("Outcome uncertain", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open group" })).toHaveAttribute("href", "/passports/groups/00000000-0000-4000-8000-000000000001");
    const uncertain = page.getByRole("article", { name: "Workflow operation-a", exact: true });
    await expect(uncertain.getByLabel("Workflow stage")).toHaveText("Stage: dispatch cancelled unknown");
    await expect(uncertain.getByText("Workflow ID", { exact: true })).toBeVisible();
    await expect(uncertain.getByText("00000000-0000-4000-8000-000000000123", { exact: true })).toBeVisible();
    await expect(uncertain.getByText("Owning connection ID", { exact: true })).toBeVisible();
    await expect(uncertain.getByText(/Operation completed/)).toHaveCount(0);
    await expect(page.getByRole("article", { name: "Workflow operation-b", exact: true }).getByLabel("Workflow stage")).toHaveText("Stage: dispatch complete");
    await expect(page.getByRole("article", { name: "Workflow operation-c", exact: true }).getByLabel("Workflow stage")).toHaveText("Stage: dispatch cancelled");
    await expect(page.getByText("delivered", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    const workflowsScreenshot = testInfo.outputPath(`mcp-workflows-${width}.png`);
    await page.screenshot({ path: workflowsScreenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`MCP workflow outcomes ${width}px`, { path: workflowsScreenshot, contentType: "image/png" });
    const workflowCardScreenshot = testInfo.outputPath(`mcp-workflow-card-${width}.png`);
    await uncertain.screenshot({ path: workflowCardScreenshot, animations: "disabled" });
    await testInfo.attach(`MCP uncertain workflow ${width}px`, { path: workflowCardScreenshot, contentType: "image/png" });
    await page.getByRole("button", { name: "Files", exact: true }).click();
    await expect(page.getByText("Passengers.xlsx", { exact: true })).toBeVisible();
    await expect(page.getByText("available", { exact: true })).toBeVisible();
    await expect(page.getByText("Header image ready", { exact: true })).toBeVisible();
    await expect(page.getByText("Upload outcome uncertain", { exact: true })).toBeVisible();
    await expect(page.getByText("Broadcast created", { exact: true })).toBeVisible();
    await expect(page.getByText("Document draft created", { exact: true })).toBeVisible();
    await expect(page.getByText("delivered", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    const filesScreenshot = testInfo.outputPath(`mcp-files-${width}.png`);
    await page.screenshot({ path: filesScreenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`MCP files ${width}px`, { path: filesScreenshot, contentType: "image/png" });
    await page.getByRole("button", { name: "Tools", exact: true }).click();
    await expect(page.getByText("Disabled in deployment", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Protected file transfers" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    const toolsScreenshot = testInfo.outputPath(`mcp-tools-${width}.png`);
    await page.screenshot({ path: toolsScreenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`MCP tools ${width}px`, { path: toolsScreenshot, contentType: "image/png" });
    await page.getByRole("button", { name: "Connection setup", exact: true }).click();
    await expect(page.getByText(resource, { exact: true })).toBeVisible();
    const connector = page.getByRole("region", { name: "Windows connector setup" });
    await connector.getByText("Show PowerShell installation commands", { exact: true }).click();
    await expect(connector).toContainText("Windows connector 0.2.0");
    await expect(connector).toContainText("Full workflow qualification remains in progress");
    await expect(connector).not.toContainText("This deployment has not approved");
    await connector.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    const setupScreenshot = testInfo.outputPath(`mcp-setup-${width}.png`);
    await page.screenshot({ path: setupScreenshot, animations: "disabled" });
    await testInfo.attach(`MCP connector setup ${width}px`, { path: setupScreenshot, contentType: "image/png" });
    expect(state.requests.filter((item) => item.method === "PATCH")[0].body).toEqual({ name: "Travel laptop", capabilities: ["mcp:read"] });
    expect(state.errors).toEqual([]);
  });
}

test("a non-superadmin direct URL never mounts MCP requests", async ({ page }) => {
  const state = await setup(page, "agency_staff");
  await page.goto("/admin/mcp");
  await expect.poll(async () => new URL(page.url()).pathname === "/passports"
    || await page.getByRole("heading", { name: "This workspace is not available to your current role" }).isVisible()).toBe(true);
  await expect(page.getByRole("link", { name: "MCP", exact: true })).toHaveCount(0);
  expect(state.requests).toEqual([]);
});

test("consent binds the chosen authority and returns opaque OAuth state to the approved client", async ({ page }, testInfo) => {
  const state = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(`${callback}?**`, (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Connection received by client</h1>" }));
  await page.goto(`/admin/mcp/connect?${new URLSearchParams(oauth)}`);
  await expect(page.getByRole("heading", { name: "Connect to Global Connects" })).toBeVisible();
  await page.getByRole("textbox", { name: "Connection name" }).fill("Nipun’s desktop");
  await page.getByRole("checkbox", { name: /Exports/ }).uncheck();
  const screenshot = testInfo.outputPath("mcp-consent-mobile.png");
  await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
  await testInfo.attach("MCP consent mobile", { path: screenshot, contentType: "image/png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  await page.getByRole("button", { name: "Authorize connection" }).scrollIntoViewIfNeeded();
  const footerScreenshot = testInfo.outputPath("mcp-consent-mobile-footer.png");
  await page.screenshot({ path: footerScreenshot, animations: "disabled" });
  await testInfo.attach("MCP consent mobile controls", { path: footerScreenshot, contentType: "image/png" });
  await page.getByRole("button", { name: "Authorize connection" }).click();
  await expect(page.getByRole("heading", { name: "Connection received by client" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("state")).toBe(oauth.state);
  const authorization = state.requests.filter((item) => item.path.endsWith("/authorize"));
  expect(authorization).toHaveLength(1);
  expect(authorization[0].body).toMatchObject({ name: "Nipun’s desktop", scopes: ["mcp:read"], state: oauth.state });
  expect(state.errors).toEqual([]);
});
