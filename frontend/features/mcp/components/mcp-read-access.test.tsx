import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { mcpApi, type McpConnection, type McpInventory, type McpOverview, type McpReadAccess } from "../api/mcp.api";
import { McpAdminPage } from "./mcp-admin-page";
import { McpConsentPage } from "./mcp-consent-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: Object.fromEntries(Object.keys(actual.mcpApi).map((name) => [name, vi.fn()])) };
});
const overview: McpOverview = {
  enabled: true, deployment_enabled: true, emergency_disabled: false, read_only_mode: true,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export", "mcp:change", "mcp:upload", "mcp:communicate"],
  effective_capabilities: ["mcp:read"], approved_clients: { "global-connects-desktop": ["http://127.0.0.1:8765/callback"] },
  environment: "test", revision: "test-revision", observed_at: "2026-10-01T00:00:00Z", qualification: "in_progress",
};
const connection: McpConnection = {
  id: "retained-grant", user_id: "read-admin", client_id: "global-connects-desktop", name: "My Codex connection", capabilities: overview.capabilities,
  created_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-06T00:00:00Z", last_used_at: null, revoked_at: null, status: "active",
};
const requirements = [
  { name: "list_groups", required_sections: ["all_groups", "whatsapp", "old_data"] },
  { name: "list_group_passports", required_sections: ["all_groups"] },
  { name: "resolve_group", required_sections: ["all_groups", "whatsapp"] },
];
const access: McpReadAccess = {
  read_only_mode: true, effective_capabilities: ["mcp:read"], allowed_read_sections: ["all_groups"], revision: 4,
  sections: [
    { id: "all_groups", label: "All Groups", supported: true, tool_names: ["list_groups", "list_group_passports"], tool_requirements: requirements, coverage_description: "Stored rosters; discovery also includes WhatsApp counters and retained rows." },
    { id: "whatsapp", label: "WhatsApp", supported: true, tool_names: ["list_groups"], tool_requirements: requirements.slice(0, 1), coverage_description: "Stored counters only in this fixture." },
    { id: "old_data", label: "Old Data", supported: true, tool_names: ["list_groups"], tool_requirements: requirements.slice(0, 1), coverage_description: "Retained rows." },
    { id: "settings", label: "Settings", supported: false, tool_names: [], coverage_description: "No settings read tool." },
    { id: "codex_access", label: "Codex access", supported: false, metadata_only: true, tool_names: [], coverage_description: "Connection metadata only." },
  ], connection_metadata_tools: ["connection_status"], environment: "test", backend_revision: "test-revision", observed_at: overview.observed_at,
};
const inventory: McpInventory = {
  tool_count: 4, environment: "test", revision: "test-revision", qualification: "in_progress",
  tools: [
    ...requirements.map((tool) => ({ name: tool.name, description: "Stored read", capability: "mcp:read", deployment_available: true, read_only: true, qualification: "in_progress", required_read_sections: tool.required_sections })),
    { name: "prepare_excel_export", description: "Export", capability: "mcp:export", deployment_available: true, read_only: false, qualification: "in_progress" },
    { name: "inspect_excel_export_options", description: "Export options", capability: "mcp:read", deployment_available: true, read_only: true, qualification: "in_progress" },
  ], file_transports: [{ name: "download_prepared_artifact", capability: "mcp:export" }],
};
const clients: QueryClient[] = [];
function renderPage(component = <McpAdminPage section="settings" />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
  return client;
}
async function settings() {
  await screen.findByRole("switch", { name: "Allow All Groups" });
  return screen.getByRole("region", { name: "Sidebar read access" });
}
beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: { id: connection.user_id, role: "super_admin", is_active: true } as User });
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
  vi.mocked(mcpApi.readAccess).mockResolvedValue(access);
  vi.mocked(mcpApi.inventory).mockResolvedValue(inventory);
  vi.mocked(mcpApi.activity).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.updateConnection).mockResolvedValue({ ...connection, capabilities: ["mcp:read"] });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); useAuthStore.setState({ user: null }); });

it("shows explicit coverage, supported checkboxes, metadata-only status and no unsupported toggle", async () => {
  renderPage(); const region = await settings();
  expect(within(region).getByText(access.sections[0].coverage_description!)).toBeVisible();
  expect(within(region).getByRole("switch", { name: "Allow All Groups" })).toBeChecked();
  expect(within(region).getByRole("switch", { name: "Allow WhatsApp" })).not.toBeChecked();
  expect(within(region).getByText("Not available yet")).toBeVisible();
  expect(within(region).queryByRole("switch", { name: "Allow Settings" })).not.toBeInTheDocument();
  expect(within(region).getByText("Connection metadata", { exact: true })).toBeVisible();
  expect(within(region).queryByRole("switch", { name: "Allow Codex access" })).not.toBeInTheDocument();
  expect(mcpApi.updateReadAccess).not.toHaveBeenCalled();
});

it("hides write/export/file/workflow controls despite a retained broad grant and backend inventory", async () => {
  renderPage(); await settings();
  expect(screen.getByText("Read only", { exact: true })).toBeVisible();
  expect(screen.getByRole("switch", { name: "Allow MCP access" })).toBeChecked();
  expect(screen.queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Files" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Workflows" })).not.toBeInTheDocument();
  expect(mcpApi.operations).not.toHaveBeenCalled(); expect(mcpApi.artifacts).not.toHaveBeenCalled();
});

it("does not save checkbox changes until the explicit button and displays only the confirmed response", async () => {
  vi.mocked(mcpApi.updateReadAccess).mockResolvedValue({ ...access, revision: 5, allowed_read_sections: [] });
  renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow WhatsApp" }));
  expect(mcpApi.updateReadAccess).not.toHaveBeenCalled();
  fireEvent.click(within(region).getByRole("button", { name: "Save read access" }));
  await waitFor(() => expect(mcpApi.updateReadAccess).toHaveBeenCalledWith({ allowed_read_sections: ["all_groups", "whatsapp"], expected_revision: 4 }, expect.anything()));
  expect(await within(region).findByText("Read access saved and confirmed.")).toBeVisible();
  expect(within(region).getByRole("switch", { name: "Allow WhatsApp" })).not.toBeChecked();
  expect(within(region).getByRole("switch", { name: "Allow All Groups" })).not.toBeChecked();
  expect(mcpApi.inventory).not.toHaveBeenCalled();
});

it("keeps deny changes local while saving and never announces pending success", async () => {
  let resolve!: (value: McpReadAccess) => void;
  vi.mocked(mcpApi.updateReadAccess).mockImplementation(() => new Promise((done) => { resolve = done; }));
  renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow All Groups" }));
  fireEvent.click(within(region).getByRole("button", { name: "Save read access" }));
  await waitFor(() => expect(mcpApi.updateReadAccess).toHaveBeenCalledTimes(1));
  expect(within(region).queryByText("Read access saved and confirmed.")).not.toBeInTheDocument();
  expect(within(region).getByRole("switch", { name: "Allow All Groups" })).toBeDisabled();
  await act(async () => { resolve({ ...access, revision: 5, allowed_read_sections: [] }); });
  expect(await within(region).findByText("Read access saved and confirmed.")).toBeVisible();
});

it("reports MFA failure without saving or automatically retrying the unsaved allow", async () => {
  vi.mocked(mcpApi.updateReadAccess).mockRejectedValue({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." });
  renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow WhatsApp" }));
  fireEvent.click(within(region).getByRole("button", { name: "Save read access" }));
  expect(await within(region).findByRole("alert")).toHaveTextContent("Identity confirmation was cancelled.");
  expect(within(region).queryByText("Read access saved and confirmed.")).not.toBeInTheDocument();
  expect(within(region).getByRole("switch", { name: "Allow WhatsApp" })).toBeChecked();
  expect(mcpApi.updateReadAccess).toHaveBeenCalledTimes(1);
});

it("blocks stale full-policy replacement and requires explicit reload instead of re-enabling another admin's denied section", async () => {
  const client = renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow WhatsApp" }));
  await act(async () => { client.setQueryData(["mcp-admin", "read-access"], { ...access, revision: 5, allowed_read_sections: [] }); });
  expect(await within(region).findByRole("alert")).toHaveTextContent("changed elsewhere");
  await waitFor(() => expect(within(region).getByRole("button", { name: "Save read access" })).toBeDisabled());
  vi.mocked(mcpApi.readAccess).mockResolvedValue({ ...access, revision: 5, allowed_read_sections: [] });
  fireEvent.click(within(region).getByRole("button", { name: "Reload saved settings" }));
  await waitFor(() => expect(within(region).getByRole("switch", { name: "Allow All Groups" })).not.toBeChecked());
  expect(within(region).getByRole("switch", { name: "Allow WhatsApp" })).not.toBeChecked();
  expect(mcpApi.updateReadAccess).not.toHaveBeenCalled();
});

it("does not retry a server revision conflict before reloading the actual policy", async () => {
  vi.mocked(mcpApi.updateReadAccess).mockRejectedValue({ status: 409, message: "Read access revision changed." });
  renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow WhatsApp" }));
  fireEvent.click(within(region).getByRole("button", { name: "Save read access" }));
  await waitFor(() => expect(within(region).getByRole("button", { name: "Save read access" })).toBeDisabled());
  expect(within(region).getAllByRole("alert").some((item) => item.textContent?.includes("changed elsewhere"))).toBe(true);
  expect(mcpApi.updateReadAccess).toHaveBeenCalledTimes(1);
});

it("fails closed on a read-settings fetch failure", async () => {
  vi.mocked(mcpApi.readAccess).mockRejectedValue(new Error("Read settings unavailable."));
  renderPage(); const region = await screen.findByRole("region", { name: "Sidebar read access" });
  expect(await within(region).findByRole("alert")).toHaveTextContent("Read settings unavailable.");
  expect(within(region).queryByRole("switch")).not.toBeInTheDocument();
  expect(mcpApi.updateReadAccess).not.toHaveBeenCalled();
});

it("does not treat cached settings as current after a failed refresh", async () => {
  const client = renderPage(); const region = await settings();
  fireEvent.click(within(region).getByRole("switch", { name: "Allow WhatsApp" }));
  vi.mocked(mcpApi.readAccess).mockRejectedValue(new Error("Latest policy could not be checked."));
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-admin", "read-access"] }); });
  await waitFor(() => expect(within(region).getByRole("button", { name: "Save read access" })).toBeDisabled());
  expect(within(region).getByRole("switch", { name: "Allow WhatsApp" })).toBeDisabled();
  expect(within(region).queryByText("Read access saved and confirmed.")).not.toBeInTheDocument();
});

it("removes read prompts and loads tool details only when selected", async () => {
  renderPage(); await settings();
  expect(screen.queryByText("Try a read in Codex")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy read prompt" })).not.toBeInTheDocument();
  expect(mcpApi.inventory).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Tools" }));
  await waitFor(() => expect(mcpApi.inventory).toHaveBeenCalledOnce());
});

it("reduces a broad saved connection to visible read permission on editor save", async () => {
  renderPage(<McpAdminPage />);
  const card = await screen.findByRole("article", { name: connection.name });
  fireEvent.click(await within(card).findByRole("button", { name: "Manage" }));
  expect(within(card).getAllByRole("checkbox")).toHaveLength(1);
  expect(within(card).queryByText("Download reports", { exact: true })).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(mcpApi.updateConnection).toHaveBeenCalledWith({ id: connection.id, name: connection.name, capabilities: ["mcp:read"] }, expect.anything()));
});

it("rejects an OAuth request for hidden export authority even when stored capabilities include it", async () => {
  renderPage(<McpConsentPage parameters={{ client_id: connection.client_id, redirect_uri: "http://127.0.0.1:8765/callback", resource: overview.resource,
    state: "a".repeat(32), code_challenge: "x".repeat(43), code_challenge_method: "S256", response_type: "code", scope: "mcp:read mcp:export" }} />);
  expect(await screen.findByRole("heading", { name: "Connection request could not be verified" })).toBeVisible();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument(); expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("fails closed when an older overview omits the read-only mode", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, read_only_mode: undefined, effective_capabilities: undefined });
  renderPage(); await settings();
  expect(screen.queryByRole("button", { name: "Workflows" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Files" })).not.toBeInTheDocument();
  expect(screen.queryByRole("article", { name: "Download reports" })).not.toBeInTheDocument();
});

it("hides export option metadata and file transports even when the inventory marks the options tool read-only", async () => {
  renderPage(); await settings();
  fireEvent.click(screen.getByRole("button", { name: "Tools" }));
  const tools = screen.getByRole("region", { name: "Deployed MCP tools" });
  expect(await within(tools).findByRole("heading", { name: "list groups" })).toBeVisible();
  expect(within(tools).queryByRole("heading", { name: "inspect excel export options" })).not.toBeInTheDocument();
  expect(within(tools).queryByRole("heading", { name: "prepare excel export" })).not.toBeInTheDocument();
  expect(within(tools).queryByRole("heading", { name: "Protected file transfers" })).not.toBeInTheDocument();
});

it("unmounts an already selected legacy workflow tab when the effective mode becomes read-only", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, read_only_mode: false });
  vi.mocked(mcpApi.operations).mockResolvedValue({ items: [], next_offset: null });
  const client = renderPage();
  await screen.findByRole("switch", { name: "Allow MCP access" });
  fireEvent.click(screen.getByRole("button", { name: "Workflows" }));
  await screen.findByRole("region", { name: "Saved MCP workflows" });
  await act(async () => { client.setQueryData(["mcp-admin", "overview"], overview); });
  await settings();
  expect(screen.queryByRole("region", { name: "Saved MCP workflows" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Workflows" })).not.toBeInTheDocument();
});
