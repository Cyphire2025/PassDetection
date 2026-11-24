import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { UserRole } from "@/types";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { McpAdminPage } from "./mcp-admin-page";
import { mcpAdminFixture } from "../utils/permissions.test-fixture";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, overview: vi.fn(), connections: vi.fn(), inventory: vi.fn(), activity: vi.fn(), control: vi.fn(), updateConnection: vi.fn() } };
});
const overview: McpOverview = { read_only_mode: false, enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export", "mcp:communicate"],
  approved_clients: { desktop: ["http://127.0.0.1:8765/callback"] }, environment: "qualification", revision: "abc", observed_at: "2026-09-29T00:00:00Z", qualification: "in_progress" };
const connection: McpConnection = { id: "grant-a", user_id: "admin-a", name: "Office desktop", client_id: "global-connects-desktop", capabilities: ["mcp:read", "mcp:export"],
  created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z", last_used_at: null, revoked_at: null, status: "active" };
const clients: QueryClient[] = [];
function setUser(role: UserRole = "super_admin", isActive = true) {
  useAuthStore.setState({ user: mcpAdminFixture({ id: "admin-a", role, is_active: isActive, email: "admin@example.test", full_name: "Administrator" }) });
}
function renderPage(component: React.ReactNode = <McpAdminPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  setUser();
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
  vi.mocked(mcpApi.inventory).mockResolvedValue({ tools: [], tool_count: 0, file_transports: [], environment: overview.environment, revision: overview.revision, qualification: "in_progress" });
  vi.mocked(mcpApi.activity).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.control).mockResolvedValue({ enabled: false });
  vi.mocked(mcpApi.updateConnection).mockResolvedValue(connection);
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); useAuthStore.setState({ user: null }); vi.restoreAllMocks(); });

it.each(["agency_admin", "agency_manager", "agency_staff", "agency_coordinator"] as const)("denies %s before management requests mount", (role) => {
  setUser(role);
  renderPage();
  expect(screen.getByRole("alert")).toHaveTextContent("active superadmin");
  expect(mcpApi.overview).not.toHaveBeenCalled();
  expect(mcpApi.connections).not.toHaveBeenCalled();
});
it("denies an inactive superadmin before loading connection data", () => {
  setUser("super_admin", false); renderPage();
  expect(mcpApi.connections).not.toHaveBeenCalled(); expect(mcpApi.overview).not.toHaveBeenCalled();
});
it("keeps a deployment-disabled service unavailable without showing release internals", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, enabled: false, deployment_enabled: false });
  renderPage(<McpAdminPage section="settings" />);
  expect(await screen.findByRole("switch", { name: "Allow MCP access" })).toBeDisabled();
  expect(screen.queryByText(/Release qualification/)).not.toBeInTheDocument();
  expect(screen.queryByText(overview.revision!)).not.toBeInTheDocument();
});
it("pauses then resumes even when the paused overview sets emergency_disabled", async () => {
  let current = overview;
  vi.mocked(mcpApi.overview).mockImplementation(async () => current);
  vi.mocked(mcpApi.control).mockImplementation(async (enabled) => {
    current = { ...overview, enabled, emergency_disabled: !enabled };
    return { enabled };
  });
  renderPage(<McpAdminPage section="settings" />);
  fireEvent.click(await screen.findByRole("switch", { name: "Allow MCP access" }));
  expect(mcpApi.control).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Pause access" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow MCP access" })).not.toBeChecked());
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow MCP access" })).toBeEnabled());
  fireEvent.click(screen.getByRole("switch", { name: "Allow MCP access" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Resume access" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow MCP access" })).toBeChecked());
  expect(mcpApi.control).toHaveBeenNthCalledWith(1, false, expect.anything());
  expect(mcpApi.control).toHaveBeenNthCalledWith(2, true, expect.anything());
});
it("cancels a pause without a server request and keeps saved state after MFA cancellation", async () => {
  vi.mocked(mcpApi.control).mockRejectedValue({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." });
  renderPage(<McpAdminPage section="settings" />);
  fireEvent.click(await screen.findByRole("switch", { name: "Allow MCP access" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(mcpApi.control).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("switch", { name: "Allow MCP access" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Pause access" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Identity confirmation was cancelled.");
  expect(screen.getByRole("switch", { name: "Allow MCP access" })).toBeChecked();
  expect(mcpApi.control).toHaveBeenCalledOnce();
});
it("renames a device and only allows narrowing its existing permissions", async () => {
  renderPage(); fireEvent.click(await screen.findByRole("button", { name: "Manage" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Connection name" }), { target: { value: "Travel laptop" } });
  expect(screen.queryByRole("checkbox", { name: /Send messages/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Download reports/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(mcpApi.updateConnection).toHaveBeenCalledWith({ id: "grant-a", name: "Travel laptop", capabilities: ["mcp:read"] }, expect.anything()));
});
it("restarts paginated activity at the first page when a search changes", async () => {
  vi.mocked(mcpApi.activity).mockImplementation(async (offset) => ({ items: [{ id: String(offset), action: "mcp.revoked", result: "success", entity_id: "grant-a", created_at: connection.created_at }], next_offset: offset === 0 ? 25 : null }));
  renderPage(<McpAdminPage section="settings" />);
  fireEvent.click(await screen.findByRole("button", { name: "Activity" }));
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await waitFor(() => expect(mcpApi.activity).toHaveBeenCalledWith(25, "", expect.any(AbortSignal)));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "mcp.revoked" } });
  await waitFor(() => expect(mcpApi.activity).toHaveBeenLastCalledWith(0, "mcp.revoked", expect.any(AbortSignal)));
});
