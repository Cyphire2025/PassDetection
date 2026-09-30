import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { mcpApi, type McpConnection, type McpInventory, type McpOverview } from "../api/mcp.api";
import { McpAdminPage } from "./mcp-admin-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, overview: vi.fn(), connections: vi.fn(), inventory: vi.fn(),
    activity: vi.fn(), operations: vi.fn(), artifacts: vi.fn(), control: vi.fn(), revoke: vi.fn(), authorize: vi.fn(), updateConnection: vi.fn() } };
});

const overview: McpOverview = {
  enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export"],
  approved_clients: { "global-connects-desktop": ["http://127.0.0.1:8765/callback"] },
  environment: "qualification", revision: "technical-revision-hidden", observed_at: "2026-09-30T00:00:00Z", qualification: "in_progress",
};
const connection: McpConnection = {
  id: "grant-hidden-technical-id", user_id: "simple-admin", client_id: "global-connects-desktop", name: "My Codex connection",
  capabilities: ["mcp:read", "mcp:export"], created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z",
  last_used_at: null, revoked_at: null, status: "active",
};
const inventory: McpInventory = {
  environment: "qualification", revision: overview.revision, qualification: "in_progress", tool_count: 7,
  tools: ["list_groups", "list_group_passports", "get_group_attendance_summary", "inspect_excel_export_options", "inspect_excel_export", "prepare_excel_export", "resume_excel_export"].map((name) => ({
    name, description: "Technical catalogue description", capability: ["inspect_excel_export", "prepare_excel_export", "resume_excel_export"].includes(name) ? "mcp:export" : "mcp:read",
    deployment_available: true, read_only: name.startsWith("list_") || name.startsWith("get_") || name === "inspect_excel_export_options", qualification: "in_progress",
  })),
  file_transports: [{ name: "download_prepared_artifact", capability: "mcp:export" }, { name: "acknowledge_verified_delivery", capability: "mcp:export" }],
};
const clients: QueryClient[] = [];
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><McpAdminPage /></QueryClientProvider>);
}
async function statusRegion() {
  return screen.findByRole("region", { name: "Codex connection status" });
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: connection.user_id, role: "super_admin", is_active: true } as User });
  vi.mocked(mcpApi.overview).mockResolvedValue(overview);
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [connection], next_offset: null });
  vi.mocked(mcpApi.inventory).mockResolvedValue(inventory);
  vi.mocked(mcpApi.activity).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.operations).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.artifacts).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.control).mockResolvedValue({ enabled: false });
  vi.mocked(mcpApi.revoke).mockResolvedValue({ revoked: true });
});
afterEach(() => {
  cleanup(); clients.splice(0).forEach((client) => client.clear()); useAuthStore.setState({ user: null });
});

it("opens a useful home without mounting operational detail or exposing technical catalogue", async () => {
  renderPage();
  expect(await within(await statusRegion()).findByText("Codex is authorized", { exact: true })).toBeVisible();
  expect(screen.getByRole("button", { name: "Advanced" })).toHaveAttribute("aria-expanded", "false");
  for (const name of ["Activity", "Workflows", "Files", "Tools"]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  expect(screen.queryByText(overview.revision!, { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText(connection.id, { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText("Technical catalogue description")).not.toBeInTheDocument();
  await waitFor(() => expect(mcpApi.inventory).toHaveBeenCalledTimes(1));
  for (const method of [mcpApi.activity, mcpApi.operations, mcpApi.artifacts, mcpApi.control, mcpApi.revoke, mcpApi.authorize, mcpApi.updateConnection]) expect(method).not.toHaveBeenCalled();
});

it.each([
  { name: "another administrator", value: { ...connection, user_id: "other-admin" } },
  { name: "an unrecognized client", value: { ...connection, client_id: "unrelated-client" } },
  { name: "an expired connection", value: { ...connection, status: "expired" as const } },
  { name: "a disconnected connection", value: { ...connection, status: "revoked" as const } },
])("does not present $name as this user's authorized Codex", async ({ value }) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [value], next_offset: null });
  renderPage();
  expect(await within(await statusRegion()).findByText("Sign-in needed", { exact: true })).toBeVisible();
  expect(screen.queryByText("Codex is authorized", { exact: true })).not.toBeInTheDocument();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("does not infer global disconnection from an incomplete connection page", async () => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: 25 });
  renderPage();
  expect(await within(await statusRegion()).findByText("More connections to check", { exact: true })).toBeVisible();
  expect(screen.queryByText("Sign-in needed", { exact: true })).not.toBeInTheDocument();
});

it.each([
  { enabled: false, deployment_enabled: true, emergency_disabled: true, label: "Access paused" },
  { enabled: false, deployment_enabled: false, emergency_disabled: false, label: "Not available" },
])("shows $label despite a retained authorized connection", async ({ label, ...state }) => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, ...state });
  renderPage();
  expect(await within(await statusRegion()).findByText(label, { exact: true })).toBeVisible();
  expect(screen.queryByText("Codex is authorized", { exact: true })).not.toBeInTheDocument();
  expect(mcpApi.control).not.toHaveBeenCalled();
});

it("requires a deliberate pause confirmation and cancellation sends no request", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Pause access" }));
  expect(screen.getByRole("dialog", { name: "Pause access for everyone?" })).toBeVisible();
  expect(mcpApi.control).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mcpApi.control).not.toHaveBeenCalled();
});

it("keeps the server status after rejected pause and never retries a cancelled MFA action", async () => {
  vi.mocked(mcpApi.control).mockRejectedValue({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Pause access" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Pause access" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Identity confirmation was cancelled.");
  expect(within(await statusRegion()).getByText("Codex is authorized", { exact: true })).toBeVisible();
  expect(mcpApi.control).toHaveBeenCalledTimes(1);
  expect(mcpApi.control).toHaveBeenCalledWith(false, expect.anything());
});

it("loads detailed activity only after Advanced and its specific section are opened", async () => {
  renderPage(); await statusRegion();
  fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
  expect(screen.getByRole("button", { name: "Advanced" })).toHaveAttribute("aria-expanded", "true");
  expect(mcpApi.activity).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  await waitFor(() => expect(mcpApi.activity).toHaveBeenCalledTimes(1));
  expect(mcpApi.operations).not.toHaveBeenCalled();
  expect(mcpApi.artifacts).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
  expect(screen.queryByRole("button", { name: "Activity" })).not.toBeInTheDocument();
});

it("offers the actual mixed read/export Excel workflow and copying it performs no application action", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  renderPage();
  const card = await screen.findByRole("article", { name: "Download reports" });
  await waitFor(() => expect(within(card).getByRole("button", { name: "Copy example" })).toBeEnabled());
  fireEvent.click(within(card).getByRole("button", { name: "Copy example" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("passport Excel report")));
  for (const method of [mcpApi.control, mcpApi.authorize, mcpApi.updateConnection, mcpApi.revoke]) expect(method).not.toHaveBeenCalled();
});

it.each(["inspect_excel_export_options", "inspect_excel_export", "prepare_excel_export", "resume_excel_export"])("does not advertise usable Excel export when %s is unavailable", async (name) => {
  vi.mocked(mcpApi.inventory).mockResolvedValue({ ...inventory, tools: inventory.tools.map((tool) => tool.name === name ? { ...tool, deployment_available: false } : tool) });
  renderPage();
  const card = await screen.findByRole("article", { name: "Download reports" });
  expect(await within(card).findByText("Not available here", { exact: true })).toBeVisible();
  expect(within(card).queryByRole("button", { name: "Copy example" })).not.toBeInTheDocument();
});

it.each(["download_prepared_artifact", "acknowledge_verified_delivery"])("requires the protected %s transfer before advertising an export", async (name) => {
  vi.mocked(mcpApi.inventory).mockResolvedValue({ ...inventory, file_transports: inventory.file_transports.filter((transport) => transport.name !== name) });
  renderPage();
  const card = await screen.findByRole("article", { name: "Download reports" });
  expect(await within(card).findByText("Not available here", { exact: true })).toBeVisible();
});

it.each([
  { name: "a read-only connection", items: [{ ...connection, capabilities: ["mcp:read"] as McpConnection["capabilities"] }] },
  { name: "an export-only connection", items: [{ ...connection, capabilities: ["mcp:export"] as McpConnection["capabilities"] }] },
  { name: "separate read-only and export-only connections", items: [
    { ...connection, capabilities: ["mcp:read"] as McpConnection["capabilities"] },
    { ...connection, id: "other-grant", name: "Separate export connection", capabilities: ["mcp:export"] as McpConnection["capabilities"] },
  ] },
])("does not combine authority from $name to enable the mixed Excel workflow", async ({ items }) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items, next_offset: null });
  renderPage();
  const card = await screen.findByRole("article", { name: "Download reports" });
  expect(await within(card).findByText("Permission needed", { exact: true })).toBeVisible();
  expect(within(card).getByRole("button", { name: "Copy example" })).toBeDisabled();
  expect(mcpApi.updateConnection).not.toHaveBeenCalled();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("fails closed when the catalogue cannot establish available features", async () => {
  vi.mocked(mcpApi.inventory).mockRejectedValue(new Error("Feature availability could not be checked."));
  renderPage();
  expect(await screen.findByRole("alert")).toHaveTextContent("Feature availability could not be checked.");
  const examples = screen.getByRole("region", { name: "What Codex can help with" });
  expect(within(examples).getAllByText("Not available here", { exact: true })).toHaveLength(2);
  expect(within(examples).queryByRole("button", { name: "Copy example" })).not.toBeInTheDocument();
});

it.each([null, 25])("keeps unavailable permissions distinct from incomplete discovery (next page %s)", async (next_offset) => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [{ ...connection, capabilities: ["mcp:communicate"] }], next_offset });
  renderPage();
  const region = await statusRegion();
  expect(await within(region).findByText(next_offset ? "More connections to check" : "No available permissions", { exact: true })).toBeVisible();
  expect(within(region).queryByText("Codex is authorized", { exact: true })).not.toBeInTheDocument();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("opens actionable setup from the guide and changes requested command scopes without granting access", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "How to connect" }));
  fireEvent.click(screen.getByRole("button", { name: "Open setup instructions" }));
  expect(screen.getByRole("button", { name: "Advanced" })).toHaveAttribute("aria-expanded", "true");
  expect(document.getElementById("codex-advanced-content")).toHaveFocus();
  const setup = screen.getByRole("region", { name: "Windows connector setup" });
  const read = within(setup).getByRole("radio", { name: "Look up information" });
  expect(read).toBeChecked();
  expect(within(setup).getByText(/sign-in --scopes mcp:read$/)).toBeVisible();
  fireEvent.click(within(setup).getByRole("radio", { name: "Look up information and download reports" }));
  expect(within(setup).getByText(/sign-in --scopes mcp:read mcp:export$/)).toBeVisible();
  expect(within(setup).getByText("--download-directory")).toBeVisible();
  fireEvent.click(read);
  expect(within(setup).getByText(/sign-in --scopes mcp:read$/)).toBeVisible();
  expect(within(setup).queryByText("--download-directory")).not.toBeInTheDocument();
  for (const method of [mcpApi.authorize, mcpApi.updateConnection, mcpApi.control, mcpApi.revoke]) expect(method).not.toHaveBeenCalled();
});

it("does not offer report permission in setup when that deployment permission is absent", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, capabilities: ["mcp:read"] });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "How to connect" }));
  fireEvent.click(screen.getByRole("button", { name: "Open setup instructions" }));
  expect(screen.queryByRole("radio", { name: "Look up information and download reports" })).not.toBeInTheDocument();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("disables both examples when deployment is off despite stale enabled capabilities and inventory", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, deployment_enabled: false, enabled: true });
  renderPage();
  expect(await within(await statusRegion()).findByText("Not available", { exact: true })).toBeVisible();
  const examples = screen.getByRole("region", { name: "What Codex can help with" });
  await waitFor(() => expect(within(examples).getAllByText("Not available here", { exact: true })).toHaveLength(2));
  expect(within(examples).queryByRole("button", { name: "Copy example" })).not.toBeInTheDocument();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("starts the unconnected guide without automatically granting or changing access", async () => {
  vi.mocked(mcpApi.connections).mockResolvedValue({ items: [], next_offset: null });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Connect Codex" }));
  expect(screen.getByText("Connect Codex in three steps")).toBeVisible();
  expect(screen.getByRole("button", { name: "Open setup instructions" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Advanced" })).toHaveAttribute("aria-expanded", "false");
  for (const method of [mcpApi.authorize, mcpApi.updateConnection, mcpApi.control, mcpApi.revoke]) expect(method).not.toHaveBeenCalled();
});
