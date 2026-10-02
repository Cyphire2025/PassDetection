import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { McpAdminPage } from "./mcp-admin-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, overview: vi.fn(), connections: vi.fn(), inventory: vi.fn(), revoke: vi.fn(), deleteConnection: vi.fn(), setConnectionAccess: vi.fn() } };
});

const overview: McpOverview = {
  read_only_mode: false,
  enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read"], approved_clients: {},
  environment: "qualification", revision: "fixture", observed_at: "2026-09-30T00:00:00Z", qualification: "in_progress",
};
const connection: McpConnection = {
  id: "grant-state", user_id: "admin-state", client_id: "global-connects-desktop", name: "Retained desktop",
  capabilities: ["mcp:read"], created_at: "2026-09-23T00:00:00Z", expires_at: "2026-09-30T00:00:00Z",
  last_used_at: null, revoked_at: null, status: "active",
};
const actor = { id: "admin-state", role: "super_admin", is_active: true, full_name: "Administrator" } as User;
const clients: QueryClient[] = [];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return { client, ...render(<QueryClientProvider client={client}><McpAdminPage /></QueryClientProvider>) };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: actor });
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
  vi.mocked(mcpApi.deleteConnection).mockResolvedValue({ deleted: true });
  vi.mocked(mcpApi.inventory).mockResolvedValue({ tools: [], file_transports: [], tool_count: 0, environment: overview.environment, revision: overview.revision, qualification: "in_progress" });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  useAuthStore.setState({ user: null });
});

it.each(["expired", "revoked"] as const)("retains %s connection metadata without active controls", async (status) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...connection, status,
    revoked_at: status === "revoked" ? "2026-09-29T00:00:00Z" : null }], next_offset: null });
  renderPage();
  const card = await screen.findByRole("article", { name: connection.name });
  expect(within(card).getByText(status === "expired" ? "Sign-in expired" : "Disconnected", { exact: true })).toBeVisible();
  expect(within(card).getByText("Sign in again by")).toBeVisible();
  expect(within(card).getByText("Not used yet", { exact: true })).toBeVisible();
  expect(within(card).queryByRole("button", { name: "Edit access" })).not.toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Manage" })).not.toBeInTheDocument();
  expect(within(card).getByRole("button", { name: "Delete" })).toBeEnabled();
  expect(mcpApi.revoke).not.toHaveBeenCalled();
});

it.each([
  { code: "AUTHORIZATION_ERROR", message: "MCP management requires an active superadmin account" },
  { code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." },
])("does not remove the connection or retry deletion after $code", async (error) => {
  vi.mocked(mcpApi.deleteConnection).mockRejectedValue(error);
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Manage" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete connection" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete connection" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(error.message);
  expect(within(screen.getByRole("region", { name: "MCP devices" })).getByText("Authorized", { exact: true })).toBeVisible();
  expect(mcpApi.deleteConnection).toHaveBeenCalledTimes(1);
  expect(mcpApi.revoke).not.toHaveBeenCalled();
  expect(mcpApi.connections).toHaveBeenCalledTimes(1);
});

it("removes a confirmed deletion from Devices instead of creating a disconnected row", async () => {
  vi.mocked(mcpApi.deleteConnection).mockImplementation(async () => {
    vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: null });
    return { deleted: true };
  });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete connection" }));
  await waitFor(() => expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument());
  await waitFor(() => expect(mcpApi.connections).toHaveBeenCalledTimes(2));
  expect(screen.getByText(/No approved devices yet/)).toBeVisible();
  expect(mcpApi.deleteConnection).toHaveBeenCalledWith(connection.id, expect.anything());
  expect(mcpApi.revoke).not.toHaveBeenCalled();
});

it.each(["active", "disabled", "expired", "revoked"] as const)("deletes a confirmed %s connection from the list", async (status) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...connection, status, enabled: status === "active" }], next_offset: null });
  vi.mocked(mcpApi.deleteConnection).mockImplementation(async () => {
    vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: null });
    return { deleted: true };
  });
  renderPage(); fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog", { name: `Delete ${connection.name}?` })).toHaveTextContent("removes the connection from Devices and stops its MCP access");
  expect(mcpApi.deleteConnection).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete connection" }));
  await waitFor(() => expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument());
  expect(mcpApi.deleteConnection).toHaveBeenCalledOnce(); expect(mcpApi.revoke).not.toHaveBeenCalled();
});

it("supports keyboard cancellation and confirmation with safe initial focus", async () => {
  const user = userEvent.setup();
  vi.mocked(mcpApi.deleteConnection).mockImplementation(async () => {
    vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: null }); return { deleted: true };
  });
  renderPage(); const trigger = await screen.findByRole("button", { name: "Delete" }); trigger.focus();
  await user.keyboard("{Enter}");
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" })).toHaveFocus();
  await user.keyboard("{Enter}"); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mcpApi.deleteConnection).not.toHaveBeenCalled();
  trigger.focus(); await user.keyboard("{Enter}"); await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(mcpApi.deleteConnection).not.toHaveBeenCalled();
  trigger.focus(); await user.keyboard("{Enter}"); await user.tab();
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete connection" })).toHaveFocus();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument());
  expect(mcpApi.deleteConnection).toHaveBeenCalledOnce();
});

it("keeps the row while deletion is pending and blocks duplicate or competing actions", async () => {
  let confirm!: (value: { deleted: true }) => void;
  vi.mocked(mcpApi.deleteConnection).mockImplementation(() => new Promise((resolve) => { confirm = resolve; }));
  renderPage(); const row = await screen.findByRole("article", { name: connection.name });
  fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("dialog"); fireEvent.click(within(dialog).getByRole("button", { name: "Delete connection" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "Delete connection" })).toBeDisabled());
  expect(row).toBeVisible();
  for (const name of ["Delete", "Disable", "Manage"]) expect(within(row).getByRole("button", { name })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete connection" }));
  expect(mcpApi.deleteConnection).toHaveBeenCalledOnce();
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: null });
  await act(async () => confirm({ deleted: true }));
  await waitFor(() => expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument());
  expect(mcpApi.setConnectionAccess).not.toHaveBeenCalled();
});

it("removes only the confirmed connection from every cached page even if the refresh fails", async () => {
  const remaining = { ...connection, id: "grant-other", name: "My MacBook" };
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection, remaining], next_offset: null });
  vi.mocked(mcpApi.deleteConnection).mockImplementation(async () => {
    vi.mocked(mcpApi.connections).mockRejectedValue(new Error("The list could not be refreshed.")); return { deleted: true };
  });
  const { client } = renderPage();
  await screen.findByRole("article", { name: connection.name });
  client.setQueryData(["mcp-admin", "connections", 25], { items: [connection, remaining], next_offset: null });
  fireEvent.click(within(screen.getByRole("article", { name: connection.name })).getByRole("button", { name: "Delete" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete connection" }));
  await waitFor(() => expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument());
  expect(screen.getByRole("article", { name: remaining.name })).toBeVisible();
  expect(client.getQueryData(["mcp-admin", "connections", 25])).toEqual({ items: [remaining], next_offset: null });
});

it("removes cached management content immediately when the active actor loses the superadmin role", async () => {
  renderPage();
  await screen.findByRole("article", { name: connection.name });
  act(() => useAuthStore.setState({ user: { ...actor, role: "agency_staff" } }));
  expect(screen.getByRole("alert")).toHaveTextContent("active superadmin");
  expect(screen.queryByRole("article", { name: connection.name })).not.toBeInTheDocument();
  expect(mcpApi.connections).toHaveBeenCalledTimes(1);
  expect(mcpApi.revoke).not.toHaveBeenCalled();
});
