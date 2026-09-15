import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GcAppGroupControl } from "../types";
import { AppControlGroupWorkspace } from "./app-control-group-workspace";

const queries = vi.hoisted(() => ({ control: vi.fn(), content: vi.fn(), announcements: vi.fn(), history: vi.fn(), actions: vi.fn() }));
vi.mock("../hooks/use-gc-app-admin", () => ({
  useGcAppGroupControl: queries.control, useGcAppGroupContent: queries.content,
  useGcAppAnnouncements: queries.announcements, useGcAppGroupAudit: queries.history,
  useGcAppGroupMutations: queries.actions,
}));
vi.mock("./gc-app-agency-scope", () => ({ useGcAppAgencyScope: () => ({ agencyId: "agency-1" }) }));

const CONTROL: GcAppGroupControl = {
  id: "trip-1", name: "Singapore trip", lifecycle: "closed", destination: "Singapore", start_date: null, end_date: null,
  company: { id: "company-1", name: "Example Client" }, gc_app_enabled: true, my_photos_enabled: false,
  passenger_access_enabled: true, client_manager_access_enabled: true, coordinator_access_enabled: true,
  access_starts_at: null, access_expires_at: null, access_revoked_at: null, revision: 1, organization_id: "company-1",
  active_mobile_users: 3, synced_device_count: 2, last_successful_sync_at: null,
  versions: { itinerary_version: 2, common_document_version: 8, announcement_version: 9 },
  app_availability: "active", app_availability_reason: null, app_availability_evaluated_at: "2026-09-15T12:00:00Z",
};
const page = { items: [], total: 0, page: 1, page_size: 25, has_next: false };
const result = (data: unknown, extra = {}) => ({ data, isLoading: false, isError: false, isFetching: false, refetch: vi.fn(), ...extra });
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.resetAllMocks();
  queries.control.mockReturnValue(result(CONTROL));
  queries.content.mockReturnValue(result(undefined));
  queries.announcements.mockReturnValue(result(undefined));
  queries.history.mockReturnValue(result(undefined));
  queries.actions.mockReturnValue(Object.fromEntries([
    "updateControl", "setMyPhotosEnabled", "revoke", "uploadDocument", "setDocumentPublished", "reorderDocuments",
    "deleteDocument", "previewDocument", "createAnnouncement", "updateAnnouncement", "setAnnouncementPublished", "deleteAnnouncement",
  ].map((name) => [name, { isPending: false, mutateAsync: vi.fn().mockResolvedValue(undefined) }])));
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const ui = <QueryClientProvider client={client}><AppControlGroupWorkspace groupId="trip-1" /></QueryClientProvider>;
  const view = render(ui);
  return { ...view, refresh: () => view.rerender(<QueryClientProvider client={client}><AppControlGroupWorkspace groupId="trip-1" /></QueryClientProvider>) };
}

describe("Trip-centric GC App workspace", () => {
  it("opens the overview and lazily fetches content and history when selected", async () => {
    renderWorkspace();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("App: Available now")).toBeVisible();
    expect(screen.getByText("Closed")).toBeVisible();
    expect(queries.content).toHaveBeenLastCalledWith("agency-1", "trip-1", false);
    expect(queries.announcements).toHaveBeenLastCalledWith("agency-1", "trip-1", 1, 25, false);
    expect(queries.history).toHaveBeenLastCalledWith("agency-1", "trip-1", 1, 25, false);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Documents" }));
    expect(queries.content).toHaveBeenLastCalledWith("agency-1", "trip-1", true);
    expect(queries.history).toHaveBeenLastCalledWith("agency-1", "trip-1", 1, 25, false);
  });

  it("preserves unsaved date edits through other tabs and unrelated revisions", async () => {
    const view = renderWorkspace();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Access & features" }));
    fireEvent.change(screen.getByLabelText("Access expires"), { target: { value: "2027-01-01T15:00" } });
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    queries.control.mockReturnValue(result({ ...CONTROL, revision: 2, my_photos_enabled: true }));
    view.refresh();
    await user.click(screen.getByRole("tab", { name: "Access & features" }));
    expect(screen.getByLabelText("Access expires")).toHaveValue("2027-01-01T15:00");
    expect(screen.getByRole("button", { name: "Save access window" })).toBeEnabled();
  });

  it("retains announcement edits when refresh fails and disables writes until recovery", async () => {
    queries.announcements.mockReturnValue(result(page));
    const view = renderWorkspace();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Announcements" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Unsaved trip update" } });
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    queries.announcements.mockReturnValue(result(page, { isError: true }));
    view.refresh();
    await user.click(screen.getByRole("tab", { name: "Announcements" }));
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Unsaved trip update");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Your draft is kept");
    queries.announcements.mockReturnValue(result(page));
    view.refresh();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });

  it("loads bounded history pages and exposes keyboard tab navigation", async () => {
    queries.history.mockReturnValue(result({ ...page, total: 26, has_next: true, items: [
      { id: "event-1", action: "gc_app.group_enabled", summary: "App access enabled", actor_name: "Staff", created_at: "2026-09-15T12:00:00Z" },
    ] }));
    renderWorkspace();
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "End" });
    expect(screen.getByRole("tab", { name: "History" })).toHaveFocus();
    expect(queries.history).toHaveBeenLastCalledWith("agency-1", "trip-1", 1, 25, true);
    const panel = screen.getByRole("tabpanel", { name: "History" });
    expect(within(panel).getByText("App access enabled")).toBeVisible();
    await userEvent.setup().click(within(panel).getByRole("button", { name: "Next" }));
    expect(queries.history).toHaveBeenLastCalledWith("agency-1", "trip-1", 2, 25, true);
  });
});
