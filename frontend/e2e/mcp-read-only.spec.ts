import { expect, test, type Page, type Route } from "@playwright/test";

const resource = "https://app.example.test/mcp";
const supported = [
  ["dashboard", "Dashboard"], ["all_groups", "All Groups"], ["group_links", "Group Links"],
  ["whatsapp", "WhatsApp"], ["operations_inbox", "Operations Inbox"], ["documents", "Documents"],
  ["coordinators", "Coordinators"], ["rooming_lists", "Rooming Lists"], ["menu", "Menu"],
  ["tour_ops", "Tour Ops"], ["gc_app", "GC App"], ["manager", "Manager"],
  ["staff", "Staff"], ["analytics", "Analytics"], ["old_data", "Old Data"],
];
const requirements = [{ name: "list_groups", required_sections: ["all_groups", "whatsapp", "old_data"] }];

async function setup(page: Page) {
  const errors: string[] = [];
  const mutations: Array<{ path: string; body: unknown }> = [];
  let allowed = ["all_groups"];
  let revision = 4;
  let conflict = false;
  const user = { id: "readonly-test-admin", email: "mcp@example.test", full_name: "MCP Test Administrator",
    role: "super_admin", agency_id: null, is_active: true, capabilities: ["mcp.manage"],
    last_login_at: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
  const sections = [
    ...supported.map(([id, label]) => ({ id, label, supported: true, tool_names: id === "all_groups" ? ["list_groups"] : [],
      tool_requirements: requirements.filter((tool) => tool.required_sections.includes(id)), coverage_description: "Only the listed stored reads are available." })),
    ...[["my_tour", "My Tour"], ["audit_logs", "Audit Logs"], ["settings", "Settings"], ["codex_access", "Codex access"]].map(([id, label]) => ({
      id, label, supported: false, tool_names: [], tool_requirements: [], metadata_only: id === "codex_access",
      coverage_description: id === "codex_access" ? "Connection metadata only." : "No business read tool in this release.",
    })),
  ];
  const access = () => ({ read_only_mode: true, effective_capabilities: ["mcp:read"], allowed_read_sections: allowed,
    revision, sections, connection_metadata_tools: ["connection_status"], environment: "isolated-browser-fixture",
    backend_revision: "fixture-revision", observed_at: "2026-10-01T00:00:00Z" });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().addCookies([{ name: "access_token", value: "isolated-readonly-fixture", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/auth/refresh") return json(route, { status: "authenticated", user, token_type: "bearer", access_token_expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/api/v1/auth/me") return json(route, user);
    if (path === "/api/v1/notifications/feed") return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/mcp/read-access") {
      if (method === "GET") return json(route, access());
      if (method === "PUT") {
        mutations.push({ path, body: request.postDataJSON() });
        if (conflict) { allowed = []; revision += 1; return json(route, { detail: "Read access changed. Reload current permissions before saving." }, 409); }
        const body = request.postDataJSON();
        if (body.expected_revision !== revision) return json(route, { detail: "Unexpected fixture revision." }, 409);
        allowed = body.allowed_read_sections;
        revision += 1;
        return json(route, access());
      }
    }
    if (path === "/api/v1/admin/mcp") return json(route, { read_only_mode: true, effective_capabilities: ["mcp:read"], enabled: true,
      deployment_enabled: true, emergency_disabled: false, resource, capabilities: ["mcp:read", "mcp:export", "mcp:change", "mcp:communicate", "mcp:upload"],
      approved_clients: {}, direct_clients: { "https://chatgpt.com/oauth/codex/client.json": ["http://127.0.0.1/callback"] }, environment: "isolated-browser-fixture",
      revision: "fixture-revision", observed_at: "2026-10-01T00:00:00Z", qualification: "in_progress" });
    if (path === "/api/v1/admin/mcp/connections") return json(route, { items: [{ id: "retained-broad-grant", user_id: user.id,
      client_id: "https://chatgpt.com/oauth/codex/client.json", name: "Office desktop", device_platform: "Windows", enabled: true, capabilities: ["mcp:read", "mcp:export", "mcp:change", "mcp:communicate", "mcp:upload"],
      created_at: "2026-10-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", last_used_at: null, revoked_at: null, status: "active" }], next_offset: null });
    if (path === "/api/v1/admin/mcp/inventory") return json(route, { tool_count: 3, environment: "isolated-browser-fixture", revision: "fixture-revision", qualification: "in_progress",
      tools: [{ name: "list_groups", description: "Stored group observations", capability: "mcp:read", read_only: true, deployment_available: true,
        required_read_sections: requirements[0].required_sections, section_access_allowed: requirements[0].required_sections.every((id) => allowed.includes(id)) },
      { name: "inspect_excel_export_options", capability: "mcp:read", read_only: true, deployment_available: true },
      { name: "create_group", capability: "mcp:change", read_only: false, deployment_available: true }], file_transports: [{ name: "download_prepared_artifact", capability: "mcp:export" }] });
    if (path === "/api/v1/admin/mcp/activity") return json(route, { items: [], next_offset: null });
    if (method === "GET") return json(route, []);
    mutations.push({ path, body: request.postData() ? request.postDataJSON() : null });
    return json(route, { detail: "Unexpected mutation in isolated read-only test." }, 400);
  });
  return { errors, mutations, conflictNextSave: () => { conflict = true; } };
}

for (const width of [1440, 390]) {
  test(`read-only sidebar permissions save and conflict safely at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page);
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/admin/mcp/settings");
    const settings = page.getByRole("region", { name: "Sidebar read access" });
    await expect(settings.getByRole("switch")).toHaveCount(15);
    await expect(settings.getByRole("switch", { name: "Allow Settings" })).toHaveCount(0);
    await expect(settings.getByRole("switch", { name: "Allow My Tour" })).toHaveCount(0);
    await expect(settings.getByRole("switch", { name: "Allow Audit Logs" })).toHaveCount(0);
    await expect(settings.getByRole("switch", { name: "Allow Codex access" })).toHaveCount(0);
    await expect(settings.getByText("Connection metadata", { exact: true })).toBeVisible();
    await settings.locator("label").getByText("WhatsApp", { exact: true }).click();
    await expect(settings.getByRole("switch", { name: "Allow WhatsApp" })).toBeChecked();
    await settings.locator("label").getByText("Old Data", { exact: true }).click();
    await expect(settings.getByRole("switch", { name: "Allow Old Data" })).toBeChecked();
    expect(state.mutations).toEqual([]);
    await settings.getByRole("button", { name: "Save read access" }).click();
    await expect(settings.getByText("Read access saved and confirmed.")).toBeVisible();
    expect(state.mutations).toEqual([{ path: "/api/v1/mcp/read-access", body: { allowed_read_sections: ["all_groups", "old_data", "whatsapp"], expected_revision: 4 } }]);
    const sectionScreenshot = testInfo.outputPath(`mcp-readonly-sections-${width}.png`);
    await settings.screenshot({ path: sectionScreenshot, animations: "disabled" });
    await testInfo.attach(`Saved read sections at ${width}px`, { path: sectionScreenshot, contentType: "image/png" });
    await expect(page.getByRole("button", { name: "Files", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Workflows", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Tools", exact: true }).click();
    const tools = page.getByRole("region", { name: "Deployed MCP tools" });
    await expect(tools.getByRole("heading", { name: "list groups", exact: true })).toBeVisible();
    await expect(tools.getByRole("heading", { name: "inspect excel export options", exact: true })).toHaveCount(0);
    await expect(tools.getByRole("heading", { name: "create group", exact: true })).toHaveCount(0);
    state.conflictNextSave();
    await settings.locator("label").getByText("Menu", { exact: true }).click();
    await expect(settings.getByRole("switch", { name: "Allow Menu" })).toBeChecked();
    await settings.getByRole("button", { name: "Save read access" }).click();
    await expect(settings.getByRole("button", { name: "Save read access" })).toBeDisabled();
    await expect(settings.getByText(/Read settings changed elsewhere/)).toBeVisible();
    expect(state.mutations).toHaveLength(2);
    await settings.getByRole("button", { name: "Reload saved settings" }).click();
    await expect(settings.getByRole("switch", { name: "Allow Menu" })).not.toBeChecked();
    await expect(settings.getByRole("switch", { name: "Allow All Groups" })).not.toBeChecked();
    expect(state.mutations).toHaveLength(2);
    expect(state.errors).toEqual([]);
  });
}
