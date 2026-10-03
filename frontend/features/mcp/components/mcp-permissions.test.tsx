import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mcpApi, type McpPermissions } from "../api/mcp.api";
import { connectionFixture, permissionFixture } from "../utils/permissions.test-fixture";
import { McpPermissionsPanel } from "./mcp-permissions-panel";
import { McpConnectionCard } from "./mcp-connection-card";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: Object.fromEntries(Object.keys(actual.mcpApi).map((name) => [name, vi.fn()])) };
});
const clients: QueryClient[] = [];
function show(component: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return { client, ...render(<QueryClientProvider client={client}>{component}</QueryClientProvider>) };
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mcpApi.permissions).mockResolvedValue(permissionFixture());
  vi.mocked(mcpApi.updatePermissions).mockImplementation(async ({ expected_revision, ...values }) => permissionFixture({ ...values, permission_revision: expected_revision + 1 }));
  vi.mocked(mcpApi.updateConnectionPermissions).mockImplementation(async ({ id, expected_revision, ...values }) => connectionFixture({ id, ...values, permission_revision: expected_revision + 1 }));
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("keeps read sections when enabling writes and derives cross-section tools only from the reviewed section choices", async () => {
  show(<McpPermissionsPanel unavailable={false} />);
  const write = await screen.findByRole("region", { name: "Write settings" });
  const read = screen.getByRole("region", { name: "Read settings" });
  expect(within(read).getByRole("switch", { name: "Read All groups" })).toBeChecked();
  expect(within(read).getByRole("switch", { name: "Read Menu" })).toBeChecked();
  expect(within(write).queryByRole("switch", { name: "Write Profile" })).not.toBeInTheDocument();
  fireEvent.click(within(write).getByRole("switch", { name: "Allow write access" }));
  fireEvent.click(within(write).getByRole("switch", { name: "Write Group links" }));
  fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
  await waitFor(() => expect(mcpApi.updatePermissions).toHaveBeenCalledWith({ expected_revision: 7, read_enabled: true, write_enabled: true,
    allowed_read_sections: ["all_groups", "menu"], allowed_write_sections: ["all_groups", "exports", "group_links"],
    allowed_write_tools: ["configure_group_link", "create_group", "create_native_upload", "prepare_excel_export"] }, expect.anything()));
  expect(await screen.findByText("Permissions saved and confirmed.")).toBeVisible();
});

it("turns write authority off without discarding saved section or read choices", async () => {
  vi.mocked(mcpApi.permissions).mockResolvedValue(permissionFixture({ write_enabled: true }));
  show(<McpPermissionsPanel unavailable={false} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
  await waitFor(() => expect(mcpApi.updatePermissions).toHaveBeenCalledWith(expect.objectContaining({ write_enabled: false,
    allowed_read_sections: ["all_groups", "menu"], allowed_write_sections: ["all_groups", "exports"] }), expect.anything()));
});

it("retains pending choices, prevents repeat saves, and does not claim success when identity confirmation is cancelled", async () => {
  let fail!: (reason: unknown) => void;
  vi.mocked(mcpApi.updatePermissions).mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
  show(<McpPermissionsPanel unavailable={false} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save permissions" })).toBeDisabled());
  await waitFor(() => expect(screen.getByRole("switch", { name: "Read Menu" })).toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
  await act(async () => fail({ code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cancelled");
  expect(screen.getByRole("switch", { name: "Allow write access" })).toBeChecked();
  expect(screen.queryByText("Permissions saved and confirmed.")).not.toBeInTheDocument();
  expect(mcpApi.updatePermissions).toHaveBeenCalledOnce();
});

it("requires reload after a revision conflict and adopts the confirmed policy before another edit", async () => {
  vi.mocked(mcpApi.updatePermissions).mockRejectedValue({ status: 409, message: "Permissions changed." });
  show(<McpPermissionsPanel unavailable={false} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save permissions" }));
  await screen.findByText(/changed elsewhere/);
  expect(screen.getByRole("button", { name: "Save permissions" })).toBeDisabled();
  vi.mocked(mcpApi.permissions).mockResolvedValue(permissionFixture({ permission_revision: 9, allowed_read_sections: ["all_groups"] }));
  fireEvent.click(screen.getByRole("button", { name: "Reload saved settings" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Read Menu" })).not.toBeChecked());
  expect(screen.getByRole("switch", { name: "Allow write access" })).not.toBeChecked();
  expect(screen.queryByText(/changed elsewhere/)).not.toBeInTheDocument();
});

it("shows available read settings while deployment ceilings disable all write changes", async () => {
  vi.mocked(mcpApi.permissions).mockResolvedValue(permissionFixture({ write_available: false }));
  show(<McpPermissionsPanel unavailable={false} />);
  expect(await screen.findByRole("switch", { name: "Read Menu" })).toBeEnabled();
  expect(screen.getByRole("switch", { name: "Allow write access" })).toBeDisabled();
  expect(screen.getByRole("switch", { name: "Write Exports" })).toBeDisabled();
});

it("does not allow an old read-only connection to acquire new write scopes", async () => {
  const connection = connectionFixture({ capabilities: ["mcp:read"] });
  show(<McpConnectionCard connection={connection} readOnly={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage" }));
  await screen.findByText(/approved without write permissions/);
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow read access" })).toBeEnabled());
  expect(screen.getByRole("switch", { name: "Allow write access" })).toBeDisabled();
  fireEvent.click(screen.getByRole("switch", { name: "Allow read access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(mcpApi.updateConnectionPermissions).toHaveBeenCalledWith({ id: connection.id, expected_revision: 3,
    read_enabled: false, write_enabled: false, allowed_read_sections: null, allowed_write_sections: [] }, expect.anything()));
  expect(mcpApi.updateConnection).not.toHaveBeenCalled();
});

it("saves independent device flags while retaining the original read limit and blocking other row actions during the request", async () => {
  let complete!: (value: ReturnType<typeof connectionFixture>) => void;
  vi.mocked(mcpApi.updateConnectionPermissions).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  const connection = connectionFixture({ allowed_read_sections: ["menu"] });
  show(<McpConnectionCard connection={connection} readOnly={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow write access" })).toBeEnabled());
  fireEvent.click(screen.getByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled());
  expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Manage" })).toBeDisabled();
  expect(screen.queryByText("Device permissions saved and confirmed.")).not.toBeInTheDocument();
  expect(mcpApi.updateConnectionPermissions).toHaveBeenCalledWith({ id: connection.id, expected_revision: 3, read_enabled: true,
    write_enabled: true, allowed_read_sections: ["menu"], allowed_write_sections: ["all_groups", "exports"] }, expect.anything());
  await act(async () => complete(connectionFixture({ ...connection, write_enabled: true, allowed_write_sections: ["all_groups", "exports"], permission_revision: 4 })));
  expect(mcpApi.updateConnection).not.toHaveBeenCalled();
});

it("requires new approval or a fresh revision after a device conflict rather than retrying automatically", async () => {
  vi.mocked(mcpApi.updateConnectionPermissions).mockRejectedValue({ status: 409, message: "Reconnect for write approval." });
  show(<McpConnectionCard connection={connectionFixture()} readOnly={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Allow write access" })).toBeEnabled());
  fireEvent.click(screen.getByRole("switch", { name: "Allow write access" }));
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  expect(await screen.findByText(/Reconnect for write approval/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Save access" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reload connection" })).toBeEnabled();
  expect(mcpApi.updateConnectionPermissions).toHaveBeenCalledOnce();
});

it("blocks changes after an unsuccessful refresh even if previously verified permissions remain cached", async () => {
  const { client } = show(<McpPermissionsPanel unavailable={false} />);
  await screen.findByRole("switch", { name: "Read Menu" });
  vi.mocked(mcpApi.permissions).mockRejectedValue(new Error("Saved settings could not be checked."));
  await act(async () => { await client.invalidateQueries({ queryKey: ["mcp-admin", "permissions"] }); });
  await waitFor(() => expect(screen.getByRole("switch", { name: "Read Menu" })).toBeDisabled());
  expect(mcpApi.updatePermissions).not.toHaveBeenCalled();
});

it("fails closed when a malformed server catalog is received", async () => {
  vi.mocked(mcpApi.permissions).mockResolvedValue({ ...permissionFixture(), allowed_read_sections: null } as unknown as McpPermissions);
  show(<McpPermissionsPanel unavailable={false} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
  expect(screen.queryByRole("button", { name: "Save permissions" })).not.toBeInTheDocument();
});
