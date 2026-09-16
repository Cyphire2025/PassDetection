import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationHistoryPage } from "./notification-history-page";
import { notificationsApi } from "./notifications.api";
import { actorId, agencyId, batch } from "./notification-test-fixtures";
import type { NotificationBatch, NotificationPage } from "./notification-types";

const scope = vi.hoisted(() => ({ agencyId: "", actorId: "" }));
vi.mock("../components/gc-app-agency-scope", () => ({ useGcAppAgencyScope: () => ({ agencyId: scope.agencyId }) }));
vi.mock("@/stores/auth.store", () => ({ selectUser: vi.fn(), useAuthStore: () => scope.actorId ? { id: scope.actorId } : null }));
vi.mock("./notifications.api", () => ({ notificationsApi: { listBatches: vi.fn(), getBatch: vi.fn() } }));
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  scope.agencyId = agencyId;
  scope.actorId = actorId;
  vi.mocked(notificationsApi.listBatches).mockResolvedValue({ items: [batch], next_cursor: null });
  vi.mocked(notificationsApi.getBatch).mockResolvedValue(batch);
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const ui = () => <QueryClientProvider client={client}><NotificationHistoryPage /></QueryClientProvider>;
  const rendered = render(ui());
  return { client, rerender: () => rendered.rerender(ui()) };
}

describe("Notification history workspace", () => {
  it("shows immutable message and audience snapshots with exact provider counts and only a detail action", async () => {
    setup();
    const table = await screen.findByRole("table", { name: "Notification sends and provider status" });
    expect(within(table).getByText(batch.title)).toBeVisible();
    expect(within(table).getByText(batch.body)).toBeVisible();
    expect(within(table).getByText("1 selected trip")).toBeVisible();
    expect(within(table).getByText("2 accepted")).toBeVisible();
    expect(within(table).getByText("1 unknown")).toBeVisible();
    expect(within(table).getByText("1 read in app")).toBeVisible();
    expect(screen.getByText(/Provider acceptance does not confirm/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to notifications" })).toHaveAttribute("href", "/gc-app/notifications");
    expect(screen.queryByRole("button", { name: /edit|resend|delete|send again/i })).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 · 1 record on this page")).toBeVisible();
  });

  it("opens read-only delivery details and closes them without changing the history", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: `View delivery details for ${batch.title}` }));
    const dialog = await screen.findByRole("dialog", { name: "Notification delivery details" });
    expect(within(dialog).getByRole("heading", { name: batch.title })).toBeVisible();
    expect(within(dialog).getByText(batch.body)).toBeVisible();
    expect(within(dialog).getByText("Total recipients").nextSibling).toHaveTextContent("12");
    expect(within(dialog).getByText(/Provider accepted; phone display unconfirmed/).nextSibling).toHaveTextContent("2");
    await user.click(within(dialog).getByRole("button", { name: "Close Notification delivery details" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toBeVisible();
  });

  it("browses successive cursor pages and returns to the previous page", async () => {
    const older = { ...batch, id: "older-batch", title: "Earlier departure notice" };
    vi.mocked(notificationsApi.listBatches).mockImplementation(async (_agency, cursor) => cursor
      ? { items: [older], next_cursor: null }
      : { items: [batch], next_cursor: "next-history-cursor" });
    setup();
    const user = userEvent.setup();
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 · 1 record on this page");
    expect(notificationsApi.listBatches).toHaveBeenCalledWith(agencyId, "next-history-cursor", expect.any(AbortSignal));
    expect(within(screen.getByRole("table")).getByText(older.title)).toBeVisible();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByText("Page 1 · 1 record on this page");
    expect(within(screen.getByRole("table")).getByText(batch.title)).toBeVisible();
  });

  it.each(["agency", "actor"] as const)("resets selected detail and pagination when the %s changes", async (boundary) => {
    vi.mocked(notificationsApi.listBatches).mockResolvedValue({ items: [batch], next_cursor: "second-page" });
    const view = setup();
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 · 1 record on this page");
    await user.click(screen.getByRole("button", { name: `View delivery details for ${batch.title}` }));
    await screen.findByRole("dialog");
    vi.mocked(notificationsApi.listBatches).mockClear();
    if (boundary === "agency") scope.agencyId = "other-agency";
    else scope.actorId = "other-actor";
    view.rerender();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await screen.findByText("Page 1 · 1 record on this page");
    expect(notificationsApi.listBatches).toHaveBeenCalledWith(scope.agencyId, null, expect.any(AbortSignal));
    expect(notificationsApi.listBatches).not.toHaveBeenCalledWith(scope.agencyId, "second-page", expect.anything());
  });

  it("shows loading, then an honest empty state without a fabricated total", async () => {
    let resolve!: (page: NotificationPage<NotificationBatch>) => void;
    vi.mocked(notificationsApi.listBatches).mockReturnValue(new Promise((done) => { resolve = done; }));
    setup();
    expect(screen.getByRole("status", { name: "Loading notification history" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    resolve({ items: [], next_cursor: null });
    expect(await screen.findByRole("heading", { name: "No notifications sent yet" })).toBeVisible();
    expect(screen.getByText("Page 1 · 0 records on this page")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("supports retry after loading fails and retains loaded records on a failed refresh", async () => {
    vi.mocked(notificationsApi.listBatches).mockRejectedValueOnce(new Error("Unavailable"));
    setup();
    const user = userEvent.setup();
    expect(await screen.findByRole("alert")).toHaveTextContent("Notification history could not be loaded");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("table");
    vi.mocked(notificationsApi.listBatches).mockRejectedValueOnce(new Error("Unavailable"));
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Previously loaded records are shown");
    expect(within(screen.getByRole("table")).getByText(batch.title)).toBeVisible();
  });

  it("does not fetch history before an actor and agency are available", async () => {
    scope.actorId = "";
    const view = setup();
    expect(notificationsApi.listBatches).not.toHaveBeenCalled();
    scope.actorId = actorId;
    scope.agencyId = "";
    view.rerender();
    await waitFor(() => expect(notificationsApi.listBatches).not.toHaveBeenCalled());
  });
});
