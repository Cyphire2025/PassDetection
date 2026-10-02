import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { McpConnectionRequest, McpRequestCallback } from "../api/mcp.api";
import { mcpRequestApi, McpRequestError } from "../api/mcp-request.api";
import { mcpClientNavigation } from "../utils/consent";
import { McpRequestWaitingPage } from "./mcp-request-waiting-page";

vi.mock("../api/mcp-request.api", async (original) => {
  const actual = await original<typeof import("../api/mcp-request.api")>();
  return { ...actual, mcpRequestApi: { status: vi.fn(), finalize: vi.fn(), update: vi.fn() } };
});
const id = "eaf5b697-d6ca-4a86-bf09-3b9780139fb1";
const request: McpConnectionRequest = { id, name: "Codex device", device_platform: "Windows", client_name: "Codex", comparison_code: "V8M-2QK",
  status: "pending", requested_capabilities: ["mcp:read"], created_at: "2026-10-02T00:00:00Z", expires_at: "2026-10-02T00:10:00Z" };
const context = { client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: "http://127.0.0.1:49153/callback",
  resource: "https://app.example.test/mcp", state: "opaque-original-state-123456789" };
const callback: McpRequestCallback = { ...context, redirect_url: `${context.redirect_uri}?${new URLSearchParams({ code: "private-once-code", state: context.state, iss: "https://app.example.test" })}` };
const clients: QueryClient[] = [];
function renderWaiting(requestId: string | string[] | undefined = id) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client);
  const view = render(<StrictMode><QueryClientProvider client={client}><McpRequestWaitingPage requestId={requestId} /></QueryClientProvider></StrictMode>);
  return { client, ...view };
}
beforeEach(() => { vi.clearAllMocks(); useAuthStore.setState({ user: null }); vi.mocked(mcpRequestApi.status).mockResolvedValue(request); vi.mocked(mcpRequestApi.finalize).mockResolvedValue(callback); vi.spyOn(mcpClientNavigation, "assign").mockImplementation(() => {}); });
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); });

it("checks an anonymous request automatically without login or a request-submit step", async () => {
  renderWaiting();
  expect(await screen.findByText("Your access request is awaiting administrator approval. You can use Global Connects once an administrator approves this connection.")).toBeVisible();
  expect(screen.getByText(request.comparison_code)).toBeVisible(); expect(screen.getByText(request.name)).toBeVisible();
  expect(screen.queryByRole("button", { name: /Request access|Sign in|Log in/ })).not.toBeInTheDocument();
  expect(mcpRequestApi.status).toHaveBeenCalledWith(id, expect.any(AbortSignal)); expect(mcpRequestApi.finalize).not.toHaveBeenCalled();
});

it("finishes an approved request exactly once in StrictMode and returns only from the requester browser", async () => {
  const { client, container } = renderWaiting(); await screen.findByText(request.comparison_code);
  vi.mocked(mcpRequestApi.status).mockResolvedValue({ ...request, status: "approved" });
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-requester", id] }); });
  await waitFor(() => expect(mcpClientNavigation.assign).toHaveBeenCalledWith(callback.redirect_url));
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-requester", id] }); });
  expect(mcpRequestApi.finalize).toHaveBeenCalledOnce();
  for (const secret of [context.state, "private-once-code", context.redirect_uri]) expect(container.textContent).not.toContain(secret);
});

it("returns a declined decision using the validated access_denied callback", async () => {
  vi.mocked(mcpRequestApi.status).mockResolvedValue({ ...request, status: "rejected" });
  const declined = { ...callback, redirect_url: `${context.redirect_uri}?${new URLSearchParams({ error: "access_denied", state: context.state, iss: "https://app.example.test" })}` };
  vi.mocked(mcpRequestApi.finalize).mockResolvedValue(declined); renderWaiting();
  expect(await screen.findByRole("heading", { name: "Access request declined" })).toBeVisible();
  await waitFor(() => expect(mcpClientNavigation.assign).toHaveBeenCalledWith(declined.redirect_url));
});

it.each([
  { ...callback, redirect_url: callback.redirect_url.replace("127.0.0.1", "attacker.test") },
  { ...callback, redirect_url: `${context.redirect_uri}?${new URLSearchParams({ code: "private-once-code", state: context.state })}` },
])("does not navigate or reveal details when the final return address is invalid", async (value) => {
  vi.mocked(mcpRequestApi.status).mockResolvedValue({ ...request, status: "approved" }); vi.mocked(mcpRequestApi.finalize).mockResolvedValue(value);
  const { client, container } = renderWaiting();
  expect(await screen.findByRole("alert")).toHaveTextContent("Start Authenticate again");
  expect(mcpClientNavigation.assign).not.toHaveBeenCalled(); expect(container.textContent).not.toContain("private-once-code");
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-requester", id] }); });
  expect(mcpRequestApi.finalize).toHaveBeenCalledOnce();
});

it.each(["expired", "finalized"] as const)("shows terminal %s state without finalizing again", async (status) => {
  vi.mocked(mcpRequestApi.status).mockResolvedValue({ ...request, status, approved_capabilities: status === "finalized" ? ["mcp:read"] : null }); renderWaiting();
  expect(await screen.findByRole("heading", { name: status === "expired" ? "This request has expired" : "Connection completed" })).toBeVisible();
  expect(mcpRequestApi.finalize).not.toHaveBeenCalled();
});
it("keeps a finalized rejection declined instead of claiming the app connected", async () => {
  vi.mocked(mcpRequestApi.status).mockResolvedValue({ ...request, status: "finalized", approved_capabilities: null }); renderWaiting();
  expect(await screen.findByRole("heading", { name: "Access request declined" })).toBeVisible();
  expect(screen.getByText(/Your administrator declined this connection/)).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Connection completed" })).not.toBeInTheDocument();
  expect(mcpRequestApi.finalize).not.toHaveBeenCalled();
});

it.each(["not-a-request", [id, id]])("rejects malformed or repeated request IDs without contacting the API", (requestId) => {
  renderWaiting(requestId);
  expect(screen.getByRole("heading", { name: "Start from your MCP app" })).toBeVisible(); expect(mcpRequestApi.status).not.toHaveBeenCalled();
});
it("requires a request ID before contacting the API", () => {
  render(<McpRequestWaitingPage requestId={undefined} />);
  expect(screen.getByRole("heading", { name: "Start from your MCP app" })).toBeVisible(); expect(mcpRequestApi.status).not.toHaveBeenCalled();
});

it("shows a lost-cookie request as unavailable without dashboard login or a retry loop", async () => {
  vi.mocked(mcpRequestApi.status).mockRejectedValue(new McpRequestError(404, "private-details")); const { container } = renderWaiting();
  expect(await screen.findByRole("heading", { name: "This request is no longer available" })).toBeVisible();
  expect(container.textContent).not.toContain("private-details"); expect(screen.queryByRole("button", { name: "Check again" })).not.toBeInTheDocument();
  expect(mcpRequestApi.finalize).not.toHaveBeenCalled();
});
it("removes stale pending copy after the browser loses its request cookie", async () => {
  const { client } = renderWaiting(); await screen.findByText(request.comparison_code);
  vi.mocked(mcpRequestApi.status).mockRejectedValue(new McpRequestError(404, "unavailable"));
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-requester", id] }); });
  await screen.findByRole("heading", { name: "This request is no longer available" });
  expect(screen.queryByText(/Your access request is awaiting administrator approval/)).not.toBeInTheDocument();
  expect(screen.queryByText(request.comparison_code)).not.toBeInTheDocument();
  expect(mcpRequestApi.finalize).not.toHaveBeenCalled();
});
