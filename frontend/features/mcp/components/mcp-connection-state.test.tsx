import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { McpAdminPage } from "./mcp-admin-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, overview: vi.fn(), connections: vi.fn(), revoke: vi.fn() } };
});

const overview: McpOverview = {
  enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read"], approved_clients: {},
  environment: "qualification", revision: "fixture", observed_at: "2026-09-30T00:00:00Z", qualification: "in_progress",
};
const connection: McpConnection = {
  id: "grant-state", user_id: "admin-state", client_id: "desktop", name: "Retained desktop",
  capabilities: ["mcp:read"], created_at: "2026-09-23T00:00:00Z", expires_at: "2026-09-30T00:00:00Z",
  last_used_at: null, revoked_at: null, status: "active",
};
const actor = { id: "admin-state", role: "super_admin", is_active: true, full_name: "Administrator" } as User;
const clients: QueryClient[] = [];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><McpAdminPage /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: actor });
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
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
  expect(within(card).getByText(status, { exact: true })).toBeVisible();
  expect(within(card).getByText("Authorization expires")).toBeVisible();
  expect(within(card).getByText("Never", { exact: true })).toBeVisible();
  expect(within(card).queryByRole("button", { name: "Edit access" })).not.toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Revoke", exact: true })).not.toBeInTheDocument();
  expect(mcpApi.revoke).not.toHaveBeenCalled();
});

it.each([
  { code: "AUTHORIZATION_ERROR", message: "MCP management requires an active superadmin account" },
  { code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." },
])("does not claim revocation or retry after $code", async (error) => {
  vi.mocked(mcpApi.revoke).mockRejectedValue(error);
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Revoke", exact: true }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke connection" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(error.message);
  expect(within(screen.getByRole("article", { name: connection.name })).getByText("active", { exact: true })).toBeVisible();
  expect(mcpApi.revoke).toHaveBeenCalledTimes(1);
  expect(mcpApi.connections).toHaveBeenCalledTimes(1);
});

it("refetches durable state after successful revocation and keeps the retained connection visible", async () => {
  vi.mocked(mcpApi.revoke).mockImplementation(async () => {
    vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...connection, status: "revoked",
      revoked_at: "2026-09-30T00:00:00Z" }], next_offset: null });
    return { revoked: true };
  });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Revoke", exact: true }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke connection" }));
  await waitFor(() => expect(within(screen.getByRole("article", { name: connection.name })).getByText("revoked", { exact: true })).toBeVisible());
  expect(mcpApi.connections).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("button", { name: "Revoke", exact: true })).not.toBeInTheDocument();
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
