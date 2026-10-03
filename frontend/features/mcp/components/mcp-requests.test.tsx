import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mcpApi, type McpConnectionRequest, type McpOverview } from "../api/mcp.api";
import { McpRequests } from "./mcp-requests";
import { permissionFixture } from "../utils/permissions.test-fixture";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, requests: vi.fn(), approveRequest: vi.fn(), rejectRequest: vi.fn(), permissions: vi.fn() } };
});
const overview: McpOverview = { enabled: true, deployment_enabled: true, emergency_disabled: false, read_only_mode: true,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export"], effective_capabilities: ["mcp:read"], approved_clients: {},
  environment: "test", revision: "test", observed_at: "2026-10-02T00:00:00Z", qualification: "in_progress" };
const request: McpConnectionRequest = { id: "request-a", name: "Codex device", device_platform: "Windows", client_name: "Codex",
  comparison_code: "V8M-2QK", status: "pending", requested_capabilities: ["mcp:read", "mcp:export"],
  created_at: "2026-10-02T00:00:00Z", expires_at: "2026-10-02T00:10:00Z" };
const clients: QueryClient[] = [];
function renderRequests(value = overview) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const view = render(<QueryClientProvider client={client}><McpRequests overview={value} unavailable={false} /></QueryClientProvider>);
  return { client, ...view };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(mcpApi.requests).mockResolvedValue({ items: [request], next_offset: null }); vi.mocked(mcpApi.permissions).mockResolvedValue(permissionFixture()); });
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("shows the matching code and reviews only currently permitted requested scopes", async () => {
  vi.mocked(mcpApi.approveRequest).mockResolvedValue({ ...request, status: "approved" });
  renderRequests(); const row = await screen.findByRole("article", { name: request.name });
  expect(row).toHaveTextContent(request.comparison_code);
  expect(screen.getByText(/will use your Global Connects account/)).toBeVisible();
  fireEvent.click(within(row).getByRole("button", { name: "Approve" }));
  expect(within(row).getAllByRole("checkbox")).toHaveLength(1);
  expect(within(row).queryByRole("checkbox", { name: /Download reports/ })).not.toBeInTheDocument();
  fireEvent.change(within(row).getByRole("textbox", { name: "Device name" }), { target: { value: "  My MacBook  " } });
  fireEvent.change(within(row).getByRole("combobox", { name: "Platform" }), { target: { value: "macOS" } });
  fireEvent.click(within(row).getByRole("button", { name: "Approve connection" }));
  await waitFor(() => expect(mcpApi.approveRequest).toHaveBeenCalledWith({ id: request.id, name: "My MacBook", device_platform: "macOS", capabilities: ["mcp:read"] }, expect.anything()));
  expect(mcpApi.approveRequest).toHaveBeenCalledOnce();
});

it("does not repeat a pending approval or claim success after cancelled identity confirmation", async () => {
  let fail!: (reason: unknown) => void;
  vi.mocked(mcpApi.approveRequest).mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
  renderRequests(); const row = await screen.findByRole("article", { name: request.name });
  fireEvent.click(within(row).getByRole("button", { name: "Approve" }));
  fireEvent.click(within(row).getByRole("button", { name: "Approve connection" }));
  await waitFor(() => expect(within(row).getByRole("button", { name: "Approve connection" })).toBeDisabled());
  fireEvent.click(within(row).getByRole("button", { name: "Approve connection" }));
  await act(async () => fail({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." }));
  expect(await within(row).findByRole("alert")).toHaveTextContent("Identity confirmation was cancelled.");
  expect(mcpApi.approveRequest).toHaveBeenCalledOnce(); expect(within(row).getByText("Pending", { exact: true })).toBeVisible();
});

it("requires deliberate rejection and shows the server decision after it succeeds", async () => {
  vi.mocked(mcpApi.rejectRequest).mockImplementation(async () => {
    vi.mocked(mcpApi.requests).mockResolvedValue({ items: [{ ...request, status: "rejected", decided_at: "2026-10-02T00:03:00Z" }], next_offset: null });
    return { ...request, status: "rejected" };
  });
  renderRequests(); fireEvent.click(within(await screen.findByRole("article", { name: request.name })).getByRole("button", { name: "Reject" }));
  expect(mcpApi.rejectRequest).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reject request" }));
  expect(await screen.findByText("Rejected", { exact: true })).toBeVisible();
  expect(mcpApi.rejectRequest).toHaveBeenCalledWith(request.id, expect.anything());
});

it("blocks approval when globally paused and does not submit a stale open review", async () => {
  const { rerender, client } = renderRequests();
  fireEvent.click(within(await screen.findByRole("article", { name: request.name })).getByRole("button", { name: "Approve" }));
  rerender(<QueryClientProvider client={client}><McpRequests overview={{ ...overview, enabled: false, emergency_disabled: true }} unavailable={false} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Approve connection" })).toBeDisabled();
  fireEvent.submit(screen.getByRole("button", { name: "Approve connection" }).closest("form")!);
  expect(mcpApi.approveRequest).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
});

it("never treats cached pending requests as current after a failed refresh", async () => {
  const { client } = renderRequests(); await screen.findByRole("article", { name: request.name });
  vi.mocked(mcpApi.requests).mockRejectedValue(new Error("Requests could not be checked."));
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-admin", "requests"] }); });
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled());
  expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
});
it.each([
  { connection_id: "grant-a", label: "Connected", success: true },
  { connection_id: null, label: "Rejected", success: false },
])("shows a finalized request as $label only according to the grant outcome", async ({ connection_id, label, success }) => {
  vi.mocked(mcpApi.requests).mockResolvedValue({ items: [{ ...request, status: "finalized", connection_id }], next_offset: null });
  renderRequests();
  const badge = await within(await screen.findByRole("region", { name: "Recent request decisions" })).findByText(label, { exact: true });
  expect(badge).toBeVisible();
  if (success) expect(badge).toHaveClass("text-green-700");
  else { expect(badge).not.toHaveClass("text-green-700"); expect(screen.queryByText("Connected", { exact: true })).not.toBeInTheDocument(); }
  expect(mcpApi.approveRequest).not.toHaveBeenCalled(); expect(mcpApi.rejectRequest).not.toHaveBeenCalled();
});

it("deliberately approves a newly requested write-capable envelope with write access initially off", async () => {
  vi.mocked(mcpApi.approveRequest).mockResolvedValue({ ...request, status: "approved" });
  renderRequests({ ...overview, read_only_mode: false, effective_capabilities: ["mcp:read", "mcp:export"], permission_controls_available: true });
  fireEvent.click(within(await screen.findByRole("article", { name: request.name })).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve connection" })).toBeEnabled());
  expect(screen.getByRole("switch", { name: "Allow read access" })).toBeChecked();
  expect(screen.getByRole("switch", { name: "Allow write access" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Approve connection" }));
  await waitFor(() => expect(mcpApi.approveRequest).toHaveBeenCalledWith(expect.objectContaining({ capabilities: ["mcp:read", "mcp:export"],
    read_enabled: true, write_enabled: false, allowed_read_sections: null, allowed_write_sections: [] }), expect.anything()));
});

it("allows deliberate narrower write approval without granting scopes absent from the request", async () => {
  vi.mocked(mcpApi.approveRequest).mockResolvedValue({ ...request, status: "approved" });
  renderRequests({ ...overview, read_only_mode: false, effective_capabilities: ["mcp:read", "mcp:export", "mcp:change"], permission_controls_available: true });
  fireEvent.click(within(await screen.findByRole("article", { name: request.name })).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow write access" })).toBeEnabled());
  expect(screen.queryByRole("checkbox", { name: /Make changes/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("switch", { name: "Write All groups" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve connection" }));
  await waitFor(() => expect(mcpApi.approveRequest).toHaveBeenCalledWith(expect.objectContaining({ capabilities: ["mcp:read", "mcp:export"],
    read_enabled: true, write_enabled: true, allowed_read_sections: null, allowed_write_sections: ["exports"] }), expect.anything()));
});

it("does not submit review defaults until current global permission settings can be checked", async () => {
  vi.mocked(mcpApi.permissions).mockRejectedValue(new Error("Section settings unavailable."));
  renderRequests({ ...overview, permission_controls_available: true });
  fireEvent.click(within(await screen.findByRole("article", { name: request.name })).getByRole("button", { name: "Approve" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Section settings unavailable");
  expect(screen.getByRole("button", { name: "Approve connection" })).toBeDisabled();
  expect(mcpApi.approveRequest).not.toHaveBeenCalled();
});
