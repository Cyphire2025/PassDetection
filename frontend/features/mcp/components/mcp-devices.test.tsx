import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { accessStatus, hasPermission } from "./mcp-access-model";
import { McpDevices } from "./mcp-devices";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, connections: vi.fn(), setConnectionAccess: vi.fn(), revoke: vi.fn() } };
});
const overview: McpOverview = { read_only_mode: true, enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read"], approved_clients: {},
  environment: "test", revision: "test", observed_at: "2026-10-02T00:00:00Z", qualification: "in_progress" };
const first: McpConnection = { id: "windows-a", name: "Office Windows", device_platform: "Windows", client_id: "https://chatgpt.com/oauth/codex/client.json",
  user_id: "admin-a", enabled: true, status: "active", capabilities: ["mcp:read"], created_at: "2026-10-02T00:00:00Z",
  expires_at: "2026-10-09T00:00:00Z", last_used_at: null, revoked_at: null };
const second: McpConnection = { ...first, id: "mac-b", name: "My MacBook", user_id: "admin-b", device_platform: "macOS" };
const clients: QueryClient[] = [];
function renderDevices(unavailable = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><McpDevices overview={overview} unavailable={unavailable} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [first, second], next_offset: null });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("lists separate authorizations including another administrator without claiming physical device identity", async () => {
  renderDevices();
  const windows = await screen.findByRole("article", { name: first.name });
  const mac = screen.getByRole("article", { name: second.name });
  expect(windows).toHaveTextContent("Windows"); expect(mac).toHaveTextContent("macOS");
  expect(within(windows).getByRole("button", { name: "Disable" })).toBeEnabled();
  expect(within(mac).getByRole("button", { name: "Disable" })).toBeEnabled();
  expect(screen.getByRole("region", { name: "MCP devices" })).toHaveTextContent("cannot prove which physical computer");
  expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  expect(mcpApi.setConnectionAccess).not.toHaveBeenCalled();
});

it("disables just the chosen connection, shows confirmed state, and enables it again", async () => {
  let confirmed = [first, second];
  vi.mocked(mcpApi.connections).mockImplementation(async () => ({ items: confirmed, next_offset: null }));
  vi.mocked(mcpApi.setConnectionAccess).mockImplementation(async ({ id, enabled }) => {
    confirmed = confirmed.map((connection) => connection.id === id ? { ...connection, enabled, status: enabled ? "active" : "disabled" } : connection);
    return confirmed.find((connection) => connection.id === id)!;
  });
  renderDevices();
  fireEvent.click(within(await screen.findByRole("article", { name: first.name })).getByRole("button", { name: "Disable" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(within(screen.getByRole("article", { name: first.name })).getByRole("button", { name: "Enable" })).toBeEnabled());
  expect(mcpApi.setConnectionAccess).toHaveBeenCalledWith({ id: first.id, enabled: false }, expect.anything());
  expect(within(screen.getByRole("article", { name: second.name })).getByRole("button", { name: "Disable" })).toBeEnabled();
  fireEvent.click(within(screen.getByRole("article", { name: first.name })).getByRole("button", { name: "Enable" }));
  await waitFor(() => expect(within(screen.getByRole("article", { name: first.name })).getByRole("button", { name: "Disable" })).toBeEnabled());
  expect(mcpApi.setConnectionAccess).toHaveBeenLastCalledWith({ id: first.id, enabled: true }, expect.anything());
  expect(mcpApi.setConnectionAccess).toHaveBeenCalledTimes(2);
  expect(mcpApi.revoke).not.toHaveBeenCalled();
});

it("keeps authorization visible while a disable is pending and does not repeat the request", async () => {
  let complete!: (value: McpConnection) => void;
  vi.mocked(mcpApi.setConnectionAccess).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  renderDevices();
  const card = await screen.findByRole("article", { name: first.name });
  fireEvent.click(within(card).getByRole("button", { name: "Disable" }));
  await waitFor(() => expect(within(card).getByRole("button", { name: "Disable" })).toBeDisabled());
  expect(within(card).getByText("Authorized", { exact: true })).toBeVisible();
  fireEvent.click(within(card).getByRole("button", { name: "Disable" }));
  expect(mcpApi.setConnectionAccess).toHaveBeenCalledTimes(1);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...first, status: "disabled", enabled: false }, second], next_offset: null });
  await act(async () => complete({ ...first, status: "disabled", enabled: false }));
  await waitFor(() => expect(within(card).getByRole("button", { name: "Enable" })).toBeEnabled());
});

it.each(["Identity confirmation was cancelled.", "Access could not be saved."])("does not claim changed access or retry when the server returns %s", async (message) => {
  vi.mocked(mcpApi.setConnectionAccess).mockRejectedValue(new Error(message));
  renderDevices();
  const card = await screen.findByRole("article", { name: first.name });
  fireEvent.click(within(card).getByRole("button", { name: "Disable" }));
  expect(await within(card).findByRole("alert")).toHaveTextContent(message);
  expect(within(card).getByRole("button", { name: "Disable" })).toBeEnabled();
  expect(within(card).getByText("Authorized", { exact: true })).toBeVisible();
  expect(mcpApi.setConnectionAccess).toHaveBeenCalledTimes(1);
  expect(mcpApi.connections).toHaveBeenCalledTimes(1);
});

it.each(["expired", "revoked"] as const)("retains %s metadata without offering Enable", async (status) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...first, status, enabled: false }], next_offset: null });
  renderDevices(); await screen.findByRole("article", { name: first.name });
  expect(screen.queryByRole("button", { name: "Enable" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
});

it("fails closed on a disabled connection even if a stale status says active", () => {
  const retained = { ...first, enabled: false };
  expect(hasPermission([retained], ["mcp:read"])).toBe(false);
  expect(accessStatus(overview, [retained], false, false).authorized).toBe(false);
});

it("disables controls while the overview cannot be verified", async () => {
  renderDevices(true);
  const card = await screen.findByRole("article", { name: first.name });
  expect(within(card).getByRole("button", { name: "Disable" })).toBeDisabled();
  expect(mcpApi.setConnectionAccess).not.toHaveBeenCalled();
});
