import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppControlsPage } from "./app-controls-page";

const http = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: http }));
vi.mock("./gc-app-agency-scope", () => ({
  useGcAppAgencyScope: () => ({ agencyId: "agency-1", isReady: true }),
}));

const ROOT = "/api/v1/gc-app/admin";
const COMPANY = { id: "company-1", name: "Example Client", status: "active" };
const CLIENTS: QueryClient[] = [];

function group(lifecycle: "active" | "closed", revision?: number) {
  return {
    id: `group-${lifecycle}`,
    name: `${lifecycle === "active" ? "Open" : "Closed"} collection group`,
    destination: "Singapore",
    travel_date: "2026-11-01",
    return_date: "2026-11-08",
    lifecycle_status: lifecycle,
    gc_enabled: false,
    access: revision === undefined ? null : { revision },
  };
}

function mockDirectory(candidates: ReturnType<typeof group>[]) {
  http.get.mockImplementation(async (url: string, { params }: { params: Record<string, unknown> }) => {
    if (url === `${ROOT}/client-organizations/search`) {
      return { data: { items: [COMPANY], total: 1, offset: 0, limit: 20 } };
    }
    if (url === `${ROOT}/groups`) {
      return { data: {
        items: params.eligible_only ? candidates.slice(Number(params.offset), Number(params.offset) + Number(params.limit)) : [],
        total: params.eligible_only ? candidates.length : 0,
        offset: Number(params.offset),
        limit: Number(params.limit),
      } };
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

function renderControls() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  CLIENTS.push(client);
  render(<QueryClientProvider client={client}><AppControlsPage /></QueryClientProvider>);
}

async function openPicker(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getAllByRole("button", { name: "Add group to GC App" })[0]!);
  return screen.findByRole("dialog", { name: "Add group to GC App" });
}

async function selectCompany(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) {
  await user.click(within(dialog).getByRole("combobox", { name: /Assigned company\/client/ }));
  await user.click(await screen.findByRole("option", { name: COMPANY.name }));
}

function addButton(dialog: HTMLElement, name: string) {
  const row = within(dialog).getByText(name).parentElement!.parentElement!;
  return within(row).getByRole("button", { name: "Add" });
}

beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  cleanup();
  CLIENTS.splice(0).forEach((client) => client.clear());
});

describe("GC App Controls collection-independent group picker", () => {
  it("keeps a configured paused trip visible and filters by app availability", async () => {
    http.get.mockResolvedValue({ data: { items: [{ ...group("closed"), access: {
      group_id: "group-closed", enabled: false, passenger_access_enabled: true,
      client_manager_access_enabled: true, coordinator_access_enabled: false,
      access_starts_at: null, access_expires_at: null, revoked_at: "2026-09-15T12:00:00Z",
      itinerary_version: 0, common_document_version: 0, announcement_version: 0, revision: 4,
      last_successful_sync_at: null, app_availability: "paused", app_availability_reason: "app_disabled",
    } }], total: 1, offset: 0, limit: 20 } });
    const user = userEvent.setup();
    renderControls();
    expect(await screen.findByRole("link", { name: "Open trip" })).toHaveAttribute("href", "/gc-app/app-controls/group-closed");
    expect(screen.getByText("Paused")).toBeVisible();
    expect(screen.getByText(/Passport collection: Closed/)).toBeVisible();
    await user.click(screen.getByRole("combobox", { name: /App availability/ }));
    await user.click(screen.getByRole("option", { name: "Paused" }));
    await waitFor(() => expect(http.get).toHaveBeenCalledWith(`${ROOT}/groups`, expect.objectContaining({
      params: expect.objectContaining({ configured_only: true, availability: "paused", agency_id: "agency-1" }),
    })));
    expect(http.put).not.toHaveBeenCalled();
  });

  it.each(["active", "closed"] as const)("adds an eligible %s group through GC App access only", async (lifecycle) => {
    const candidate = group(lifecycle);
    mockDirectory([candidate]);
    http.put.mockResolvedValue({ data: {
      group_id: candidate.id,
      enabled: true,
      passenger_access_enabled: true,
      client_manager_access_enabled: true,
      coordinator_access_enabled: true,
      access_starts_at: null,
      access_expires_at: null,
      revoked_at: null,
      itinerary_version: 0,
      common_document_version: 0,
      announcement_version: 0,
      revision: 1,
      last_successful_sync_at: null,
    } });
    const user = userEvent.setup();
    renderControls();
    await screen.findByText("No GC App trips found");
    expect(http.get.mock.calls.some(([, config]) => config.params.eligible_only)).toBe(false);

    const dialog = await openPicker(user);
    await within(dialog).findByText(candidate.name);
    expect(dialog).toHaveTextContent("whether its collection link is open or closed");
    expect(addButton(dialog, candidate.name)).toBeDisabled();
    expect(http.get).toHaveBeenCalledWith(`${ROOT}/groups`, expect.objectContaining({
      params: { agency_id: "agency-1", eligible_only: true, unconfigured_only: true, q: undefined, offset: 0, limit: 20 },
    }));

    await selectCompany(user, dialog);
    await user.click(addButton(dialog, candidate.name));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(http.put).toHaveBeenCalledExactlyOnceWith(`${ROOT}/groups/${candidate.id}`, {
      client_organization_id: COMPANY.id,
      enabled: true,
      passenger_access_enabled: true,
      client_manager_access_enabled: true,
      coordinator_access_enabled: true,
      access_starts_at: null,
      access_expires_at: null,
      expected_revision: null,
    }, { params: { agency_id: "agency-1" } });
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).not.toHaveBeenCalled();
  });

  it("keeps a closed group's revision conflict visible without retrying or reopening collection", async () => {
    const candidate = group("closed", 7);
    mockDirectory([candidate]);
    http.put.mockRejectedValue({ message: "GC App settings changed; refresh and retry", status: 409 });
    const user = userEvent.setup();
    renderControls();
    const dialog = await openPicker(user);
    await within(dialog).findByText(candidate.name);
    await selectCompany(user, dialog);
    await user.click(addButton(dialog, candidate.name));

    expect(await within(dialog).findByRole("alert"))
      .toHaveTextContent("GC App settings changed; refresh and retry");
    expect(http.put).toHaveBeenCalledTimes(1);
    expect(http.put.mock.calls[0]?.[1]).toMatchObject({ expected_revision: 7, enabled: true });
    expect(http.put.mock.calls[0]?.[1]).not.toHaveProperty("lifecycle_status");
    expect(http.put.mock.calls[0]?.[1]).not.toHaveProperty("status");
    expect(addButton(dialog, candidate.name)).toBeEnabled();
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).not.toHaveBeenCalled();
  });

  it("preserves server pagination when eligible results include closed groups", async () => {
    mockDirectory([
      ...Array.from({ length: 20 }, (_, index) => ({
        ...group("active"), id: `group-${index}`, name: `Open collection group ${index + 1}`,
      })),
      group("closed"),
    ]);
    const user = userEvent.setup();
    renderControls();
    const dialog = await openPicker(user);
    await within(dialog).findByText("Open collection group 1");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(await within(dialog).findByText("Closed collection group")).toBeVisible();
    await waitFor(() => expect(http.get).toHaveBeenCalledWith(`${ROOT}/groups`, expect.objectContaining({
      params: { agency_id: "agency-1", eligible_only: true, unconfigured_only: true, q: undefined, offset: 20, limit: 20 },
    })));
  });

  it("describes an empty eligible result without claiming collection must be open", async () => {
    mockDirectory([]);
    const user = userEvent.setup();
    renderControls();
    const dialog = await openPicker(user);
    expect(await within(dialog).findByText("No eligible non-archived groups found.")).toBeVisible();
    expect(dialog).not.toHaveTextContent("Only active eligible groups");
  });
});
