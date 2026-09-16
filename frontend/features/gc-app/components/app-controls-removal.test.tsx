import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppControlsPage } from "./app-controls-page";

const http = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
const session = vi.hoisted(() => ({ agencyId: "agency-1", role: "agency_manager" }));
vi.mock("@/lib/api/client", () => ({ default: http }));
vi.mock("@/stores/auth.store", () => ({ selectUser: () => undefined, useAuthStore: () => ({ role: session.role }) }));
vi.mock("./gc-app-agency-scope", () => ({ useGcAppAgencyScope: () => ({ agencyId: session.agencyId, isReady: true }) }));
const ROOT = "/api/v1/gc-app/admin";
const clients: QueryClient[] = [];

function group(id = "trip", lifecycle = "archived") {
  return { id, name: `Old group ${id}`, destination: "Dubai", lifecycle_status: lifecycle,
    travel_date: null, return_date: null, gc_enabled: false, access: {
      group_id: id, name: `Old group ${id}`, lifecycle_status: lifecycle,
      enabled: false, passenger_access_enabled: false, client_manager_access_enabled: false,
      coordinator_access_enabled: false, access_starts_at: null, access_expires_at: null,
      revoked_at: "2026-09-15T12:00:00Z", removed_at: null as string | null,
      revision: 7, last_successful_sync_at: null, active_mobile_users: 0, synced_device_count: 0,
      itinerary_version: 1, common_document_version: 1, announcement_version: 1,
      app_availability: "unavailable", app_availability_reason: "group_archived",
    } };
}

function directory(initial = [group()]) {
  const state = { groups: initial };
  http.get.mockImplementation(async (url: string, config: { params: Record<string, unknown> }) => {
    if (url === `${ROOT}/groups`) {
      const offset = Number(config.params.offset);
      const limit = Number(config.params.limit);
      const items = state.groups.filter((entry) => !entry.access.removed_at);
      return { data: { items: items.slice(offset, offset + limit), total: items.length, offset, limit } };
    }
    const current = state.groups.find((entry) => url === `${ROOT}/groups/${entry.id}`);
    if (current) return { data: current.access };
    throw new Error(`Unexpected request ${url}`);
  });
  http.delete.mockImplementation(async (url: string) => {
    const current = state.groups.find((entry) => url === `${ROOT}/groups/${entry.id}`)!;
    current.access.removed_at = "2026-09-16T12:00:00Z";
    current.access.revision++;
    return { data: undefined };
  });
  return state;
}

function renderControls() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const node = () => <QueryClientProvider client={client}><AppControlsPage /></QueryClientProvider>;
  const view = render(node());
  return { ...view, refresh: () => view.rerender(node()) };
}

async function open(user: ReturnType<typeof userEvent.setup>, name = "Old group trip") {
  await screen.findByText(name);
  const button = screen.getAllByRole("button", { name: "Remove from GC App" })[0]!;
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  return screen.getByRole("dialog", { name: "Remove group from GC App?" });
}

beforeEach(() => { vi.resetAllMocks(); session.agencyId = "agency-1"; session.role = "agency_manager"; });
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

describe("Manual GC App group removal", () => {
  it.each(["archived", "deleted"])("confirms removal of an old %s group while keeping the source records", async (lifecycle) => {
    directory([group("trip", lifecycle)]);
    const user = userEvent.setup();
    renderControls();
    let dialog = await open(user);
    expect(dialog).toHaveTextContent("The original passport group, travellers, documents and history will be kept.");
    expect(within(dialog).getByRole("button", { name: "Remove from GC App" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(http.delete).not.toHaveBeenCalled();
    dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "Old group trip");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    expect(await screen.findByText("No GC App trips found")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("The original group and its records are kept");
    expect(http.delete).toHaveBeenCalledExactlyOnceWith(`${ROOT}/groups/trip`, { params: { agency_id: "agency-1", expected_revision: 7 } });
    expect(http.put).not.toHaveBeenCalled();
    expect(http.post).not.toHaveBeenCalled();
  });

  it("hides removal from normal staff even if a page is mounted directly", async () => {
    directory(); session.role = "agency_staff";
    renderControls();
    await screen.findByText("Old group trip");
    expect(screen.queryByRole("button", { name: "Remove from GC App" })).not.toBeInTheDocument();
    expect(http.delete).not.toHaveBeenCalled();
  });

  it("requires a fresh review after a revision conflict and never retries removal automatically", async () => {
    const state = directory();
    http.delete.mockRejectedValueOnce({ message: "GC App settings changed; refresh and retry", status: 409 });
    const user = userEvent.setup(); renderControls();
    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "Old group trip");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("GC App settings changed");
    expect(http.delete).toHaveBeenCalledTimes(1);
    state.groups[0]!.access.revision = 8;
    await user.click(within(dialog).getByRole("button", { name: "Reload trip details" }));
    const input = await within(dialog).findByRole("textbox");
    expect(input).toHaveValue("");
    await user.type(input, "Old group trip");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    await screen.findByText("No GC App trips found");
    expect(http.delete).toHaveBeenCalledTimes(2);
    expect(http.delete.mock.calls[1]![1].params.expected_revision).toBe(8);
  });

  it("recovers a lost successful response by reading the removal marker without another DELETE", async () => {
    const state = directory();
    http.delete.mockImplementationOnce(async () => {
      state.groups[0]!.access.removed_at = "2026-09-16T12:00:00Z";
      state.groups[0]!.access.revision++;
      throw { message: "Connection interrupted", status: 0 };
    });
    const user = userEvent.setup(); renderControls();
    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "Old group trip");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    await user.click(await within(dialog).findByRole("button", { name: "Reload trip details" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(http.delete).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("No GC App trips found")).toBeVisible();
  });

  it.each([false, true])("returns to the previous page when the last item is removed (response lost: %s)", async (loseResponse) => {
    const state = directory(Array.from({ length: 21 }, (_, index) => group(`trip-${index}`)));
    if (loseResponse) http.delete.mockImplementationOnce(async () => {
      state.groups[20]!.access.removed_at = "2026-09-16T12:00:00Z";
      state.groups[20]!.access.revision++;
      throw { message: "Connection interrupted", status: 0 };
    });
    const user = userEvent.setup(); renderControls();
    await screen.findByText("Old group trip-0");
    await user.click(screen.getByRole("button", { name: "Next" }));
    const dialog = await open(user, "Old group trip-20");
    await user.type(within(dialog).getByRole("textbox"), "Old group trip-20");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    if (loseResponse) await user.click(await within(dialog).findByRole("button", { name: "Reload trip details" }));
    expect(await screen.findByText("Old group trip-0")).toBeVisible();
    expect(screen.getByText("Showing 1-20 of 20")).toBeVisible();
  });

  it("blocks duplicate clicks and does not show an old agency's completion in the new workspace", async () => {
    directory();
    let resolve!: (value: unknown) => void;
    http.delete.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const user = userEvent.setup(); const view = renderControls();
    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "Old group trip");
    await user.dblClick(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    expect(http.delete).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(dialog).toBeVisible();
    session.agencyId = "agency-2"; view.refresh();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => { resolve({ data: undefined }); });
    await screen.findByText("Old group trip");
    expect(screen.queryByText(/was removed from GC App/)).not.toBeInTheDocument();
    expect(http.delete.mock.calls[0]![1].params.agency_id).toBe("agency-1");
  });

  it("keeps previous-page navigation available if an uncertain removal dialog is dismissed", async () => {
    const state = directory(Array.from({ length: 21 }, (_, index) => group(`trip-${index}`)));
    http.delete.mockImplementationOnce(async () => {
      state.groups[20]!.access.removed_at = "2026-09-16T12:00:00Z";
      throw { message: "Connection interrupted", status: 0 };
    });
    const user = userEvent.setup(); renderControls();
    await screen.findByText("Old group trip-0");
    await user.click(screen.getByRole("button", { name: "Next" }));
    const dialog = await open(user, "Old group trip-20");
    await user.type(within(dialog).getByRole("textbox"), "Old group trip-20");
    await user.click(within(dialog).getByRole("button", { name: "Remove from GC App" }));
    await within(dialog).findByRole("alert");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(await screen.findByRole("button", { name: "Previous page" }));
    expect(await screen.findByText("Old group trip-0")).toBeVisible();
    expect(http.delete).toHaveBeenCalledTimes(1);
  });
});
