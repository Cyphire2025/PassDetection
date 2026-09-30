import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User, UserRole } from "@/types";
import { mcpApi, type McpConnection, type McpOverview } from "../api/mcp.api";
import { mcpClientNavigation } from "../utils/consent";
import { McpAdminPage } from "./mcp-admin-page";
import { McpConsentPage } from "./mcp-consent-page";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, overview: vi.fn(), connections: vi.fn(), inventory: vi.fn(), activity: vi.fn(), control: vi.fn(), revoke: vi.fn(), updateConnection: vi.fn(), authorize: vi.fn() } };
});
const overview: McpOverview = { enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export", "mcp:communicate"],
  approved_clients: { desktop: ["http://127.0.0.1:8765/callback"] }, environment: "qualification", revision: "abc", observed_at: "2026-09-29T00:00:00Z", qualification: "in_progress" };
const connection: McpConnection = { id: "grant-a", user_id: "admin-a", name: "Office desktop", client_id: "global-connects-desktop", capabilities: ["mcp:read", "mcp:export"],
  created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z", last_used_at: null, revoked_at: null, status: "active" };
const parameters = { client_id: "desktop", redirect_uri: "http://127.0.0.1:8765/callback", resource: overview.resource,
  state: "a".repeat(32), code_challenge: "x".repeat(43), code_challenge_method: "S256", response_type: "code", scope: "mcp:read mcp:export" };
const clients: QueryClient[] = [];
function setUser(role: UserRole = "super_admin", isActive = true) {
  useAuthStore.setState({ user: { id: "admin-a", role, is_active: isActive, email: "admin@example.test", full_name: "Administrator" } as User });
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
  vi.mocked(mcpApi.revoke).mockResolvedValue({ revoked: true });
  vi.mocked(mcpApi.updateConnection).mockResolvedValue(connection);
  vi.mocked(mcpApi.authorize).mockResolvedValue({ redirect_url: `${parameters.redirect_uri}?code=one-use&state=${parameters.state}` });
  vi.spyOn(mcpClientNavigation, "assign").mockImplementation(() => {});
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); useAuthStore.setState({ user: null }); vi.restoreAllMocks(); });

it.each(["agency_admin", "agency_manager", "agency_staff", "agency_coordinator"] as const)("denies %s before management and consent requests mount", (role) => {
  setUser(role);
  const { rerender } = renderPage();
  expect(screen.getByRole("alert")).toHaveTextContent("active superadmin");
  expect(mcpApi.overview).not.toHaveBeenCalled();
  rerender(<McpConsentPage parameters={parameters} />);
  expect(mcpApi.overview).not.toHaveBeenCalled();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});
it("denies an inactive superadmin before loading connection data", () => {
  setUser("super_admin", false); renderPage();
  expect(mcpApi.connections).not.toHaveBeenCalled(); expect(mcpApi.overview).not.toHaveBeenCalled();
});
it("shows real qualification state and keeps deployment-disabled access unavailable", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, enabled: false, deployment_enabled: false });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Advanced" }));
  expect(await screen.findByText(/Release qualification is in progress/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Resume access" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "MCP connections" })).getByRole("article", { name: "Office desktop" })).toBeVisible();
});
it("disables access through the server and confirms revocation of a named connection", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Pause access" }));
  expect(mcpApi.control).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Pause access" }));
  await waitFor(() => expect(mcpApi.control).toHaveBeenCalledWith(false, expect.anything()));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(mcpApi.revoke).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect connection" }));
  await waitFor(() => expect(mcpApi.revoke).toHaveBeenCalledWith("grant-a", expect.anything()));
});
it("renames a connection and only allows narrowing its existing permissions", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "Advanced" }));
  fireEvent.click(await screen.findByRole("button", { name: "Edit access" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Connection name" }), { target: { value: "Travel laptop" } });
  expect(screen.queryByRole("checkbox", { name: /Send messages/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Download reports/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(mcpApi.updateConnection).toHaveBeenCalledWith({ id: "grant-a", name: "Travel laptop", capabilities: ["mcp:read"] }, expect.anything()));
});
it("restarts paginated activity at the first page when a search changes", async () => {
  vi.mocked(mcpApi.activity).mockImplementation(async (offset) => ({ items: [{ id: String(offset), action: "mcp.revoked", result: "success", entity_id: "grant-a", created_at: connection.created_at }], next_offset: offset === 0 ? 25 : null }));
  renderPage(); fireEvent.click(await screen.findByRole("button", { name: "Advanced" })); fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await waitFor(() => expect(mcpApi.activity).toHaveBeenCalledWith(25, "", expect.any(AbortSignal)));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "mcp.revoked" } });
  await waitFor(() => expect(mcpApi.activity).toHaveBeenLastCalledWith(0, "mcp.revoked", expect.any(AbortSignal)));
});
it("shows versioned connector setup without claiming unpublished installation or file tools", async () => {
  renderPage(); fireEvent.click(await screen.findByRole("button", { name: "Advanced" })); fireEvent.click(screen.getByRole("button", { name: "Connection setup" }));
  const setup = screen.getByRole("region", { name: "Windows connector setup" });
  expect(setup).toHaveTextContent("Windows connector 0.2.0");
  expect(setup).toHaveTextContent("This deployment has not approved the desktop connector’s callback");
  expect(setup).toHaveTextContent("A hosted installer is not published here");
  expect(setup).toHaveTextContent("Full workflow qualification remains in progress");
  expect(setup).toHaveTextContent("PDF upload stages a file for a later workflow");
  expect(setup).toHaveTextContent("Local file tools use exact files and a download folder selected in the connector startup arguments");
  expect(setup).toHaveTextContent("Automatic handoff of new Codex attachments remains unqualified");
  expect(setup).toHaveTextContent("--origin 'https://app.example.test' sign-in --scopes mcp:read");
  expect(setup).toHaveTextContent("--require-hashes -r requirements.lock");
  expect(setup).toHaveTextContent("Secret environment variablesNone");
});
it("authorizes the reviewed name and selected scopes once, then returns only to the verified client", async () => {
  let complete!: (value: { redirect_url: string }) => void;
  vi.mocked(mcpApi.authorize).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  const { container } = renderPage(<McpConsentPage parameters={parameters} />);
  fireEvent.change(await screen.findByRole("textbox", { name: "Connection name" }), { target: { value: "Nipun’s desktop" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /Download reports/ }));
  fireEvent.submit(container.querySelector("form")!); fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(mcpApi.authorize).toHaveBeenCalledOnce());
  expect(mcpApi.authorize).toHaveBeenCalledWith(expect.objectContaining({ name: "Nipun’s desktop", scopes: ["mcp:read"], state: parameters.state }), expect.anything());
  const redirect = `${parameters.redirect_uri}?code=one-use&state=${parameters.state}`;
  await act(async () => complete({ redirect_url: redirect }));
  expect(mcpClientNavigation.assign).toHaveBeenCalledWith(redirect);
});
it("blocks unverified requests and does not follow an unexpected callback destination", async () => {
  const invalid = renderPage(<McpConsentPage parameters={{ ...parameters, resource: "https://untrusted.test/mcp" }} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
  expect(mcpApi.authorize).not.toHaveBeenCalled(); invalid.unmount();
  vi.mocked(mcpApi.authorize).mockResolvedValue({ redirect_url: "https://untrusted.test/callback?code=secret" });
  renderPage(<McpConsentPage parameters={parameters} />);
  fireEvent.change(await screen.findByRole("textbox", { name: "Connection name" }), { target: { value: "Desktop" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect app" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("callback could not be verified");
  expect(mcpClientNavigation.assign).not.toHaveBeenCalled();
});

it("offers the known Codex connection name without authorizing or adding unrequested access", async () => {
  const requested = { ...parameters, client_id: "global-connects-desktop", scope: "mcp:read" };
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview,
    approved_clients: { "global-connects-desktop": [parameters.redirect_uri] } });
  renderPage(<McpConsentPage parameters={requested} />);
  expect(await screen.findByRole("textbox", { name: "Connection name" })).toHaveValue("My Codex connection");
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
  expect(mcpClientNavigation.assign).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Connect Codex" })).toBeDisabled();
  expect(mcpApi.authorize).not.toHaveBeenCalled();
});

it("keeps disabled consent closed even with a valid prefilled request", async () => {
  vi.mocked(mcpApi.overview).mockResolvedValue({ ...overview, enabled: false, emergency_disabled: true });
  const { container } = renderPage(<McpConsentPage parameters={parameters} />);
  await screen.findByRole("textbox", { name: "Connection name" });
  expect(screen.getByRole("button", { name: "Connect app" })).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(mcpApi.authorize).not.toHaveBeenCalled();
  expect(mcpClientNavigation.assign).not.toHaveBeenCalled();
});

it("shows an authorization failure without broadening or automatically retrying the selected scopes", async () => {
  vi.mocked(mcpApi.authorize).mockRejectedValue({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." });
  renderPage(<McpConsentPage parameters={{ ...parameters, scope: "mcp:read" }} />);
  fireEvent.change(await screen.findByRole("textbox", { name: "Connection name" }), { target: { value: "My laptop" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect app" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Identity confirmation was cancelled.");
  expect(mcpApi.authorize).toHaveBeenCalledTimes(1);
  expect(mcpApi.authorize).toHaveBeenCalledWith(expect.objectContaining({ name: "My laptop", scopes: ["mcp:read"] }), expect.anything());
  expect(mcpClientNavigation.assign).not.toHaveBeenCalled();
});
