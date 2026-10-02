import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { McpAdminPage, type McpAdminSection } from "./mcp-admin-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: Object.fromEntries(Object.keys(actual.mcpApi).map((name) => [name, vi.fn()])) };
});
const overview: McpOverview = {
  read_only_mode: false, enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export"],
  approved_clients: {}, direct_clients: { "https://chatgpt.com/oauth/codex/client.json": ["http://127.0.0.1/callback"] },
  environment: "qualification", revision: "technical-revision-hidden", observed_at: "2026-09-30T00:00:00Z", qualification: "in_progress",
};
const connection: McpConnection = {
  id: "grant-hidden-id", user_id: "simple-admin", client_id: "https://chatgpt.com/oauth/codex/client.json", name: "Office Windows",
  capabilities: ["mcp:read", "mcp:export"], created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z",
  last_used_at: null, revoked_at: null, status: "active", enabled: true, device_platform: "Windows",
};
const clients: QueryClient[] = [];
function renderPage(section: McpAdminSection = "devices") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><McpAdminPage section={section} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: connection.user_id, role: "super_admin", is_active: true } as User });
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
  vi.mocked(mcpApi.requests).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.activity).mockResolvedValue({ items: [], next_offset: null });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); useAuthStore.setState({ user: null }); });

it("defaults to Devices with four real navigable pages and one connection list", async () => {
  renderPage(); await screen.findByRole("article", { name: connection.name });
  const nav = screen.getByRole("navigation", { name: "MCP pages" });
  const routes = { Devices: "/admin/mcp", Requests: "/admin/mcp/requests", Settings: "/admin/mcp/settings", "Connection setup": "/admin/mcp/setup" };
  for (const [label, path] of Object.entries(routes)) expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", path);
  expect(within(nav).getByRole("link", { name: "Devices" })).toHaveAttribute("aria-current", "page");
  expect(screen.getAllByRole("article", { name: connection.name })).toHaveLength(1);
  expect(screen.queryByRole("region", { name: "Codex connection status" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument();
  expect(screen.queryByText("Try a read in Codex")).not.toBeInTheDocument();
  expect(screen.queryByText(overview.revision!)).not.toBeInTheDocument();
  for (const method of [mcpApi.activity, mcpApi.inventory, mcpApi.requests, mcpApi.operations, mcpApi.artifacts]) expect(method).not.toHaveBeenCalled();
});

it.each(["requests", "settings", "setup"] as const)("mounts only the selected %s page", async (section) => {
  renderPage(section);
  await waitFor(() => expect(screen.getByRole("navigation", { name: "MCP pages" })).toBeVisible());
  expect(screen.queryByRole("region", { name: "MCP devices" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument();
  if (section === "requests") { await screen.findByText("No pending requests"); expect(mcpApi.connections).not.toHaveBeenCalled(); expect(mcpApi.activity).not.toHaveBeenCalled(); }
  if (section === "settings") { await screen.findByRole("switch", { name: "Allow MCP access" }); expect(mcpApi.connections).not.toHaveBeenCalled(); expect(mcpApi.inventory).not.toHaveBeenCalled(); }
  if (section === "setup") { await screen.findByRole("region", { name: "Direct MCP setup" }); expect(mcpApi.activity).not.toHaveBeenCalled(); expect(mcpApi.inventory).not.toHaveBeenCalled(); }
});

it("shows the native URL instructions and copies the URL without granting access", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  renderPage("setup");
  const setup = await screen.findByRole("region", { name: "Direct MCP setup" });
  expect(setup).toHaveTextContent("Streamable HTTP"); expect(setup).toHaveTextContent(overview.resource);
  expect(setup).toHaveTextContent("comparison code"); expect(setup).toHaveTextContent("automatically");
  expect(setup).not.toHaveTextContent("PowerShell");
  fireEvent.click(screen.getByRole("button", { name: "Copy MCP URL" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(overview.resource));
  for (const method of [mcpApi.authorize, mcpApi.updateConnection, mcpApi.control, mcpApi.revoke]) expect(method).not.toHaveBeenCalled();
});

it.each([
  { ...connection, user_id: "other-admin" }, { ...connection, client_id: "unrelated-client" },
  { ...connection, status: "expired" as const }, { ...connection, status: "revoked" as const },
])("does not present an unrelated or inactive grant as this account's authorized app", async (value) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [value], next_offset: null }); renderPage("setup");
  expect(await within(await screen.findByRole("region", { name: "Codex connection status" })).findByText("Approval needed", { exact: true })).toBeVisible();
  expect(screen.queryByText("Codex is authorized", { exact: true })).not.toBeInTheDocument();
});

it.each([
  { enabled: false, deployment_enabled: true, emergency_disabled: true, label: "Access paused" },
  { enabled: false, deployment_enabled: false, emergency_disabled: false, label: "Not available" },
])("shows $label despite a retained grant", async ({ label, ...state }) => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, ...state }); renderPage("setup");
  expect(await within(await screen.findByRole("region", { name: "Codex connection status" })).findByText(label, { exact: true })).toBeVisible();
});

it("keeps incomplete discovery distinct from needing approval", async () => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: 25 }); renderPage("setup");
  expect(await screen.findByText("More connections to check", { exact: true })).toBeVisible();
  expect(screen.queryByText("Approval needed", { exact: true })).not.toBeInTheDocument();
});
