import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { notificationsApi } from "./notifications.api";
import { NotificationsPage } from "./notifications-page";
import { agencyId, actorId, batch, draft, group, preview } from "./notification-test-fixtures";
import { persistPendingSend, pendingSendKey } from "./pending-send";

vi.mock("../components/gc-app-agency-scope", () => ({ useGcAppAgencyScope: () => ({ agencyId: "10000000-0000-4000-8000-000000000001" }) }));
vi.mock("@/stores/auth.store", () => ({ selectUser: vi.fn(), useAuthStore: () => ({ id: "20000000-0000-4000-8000-000000000001" }) }));
vi.mock("../api/gc-app-admin.api", () => ({ gcAppAdminApi: { listGroups: vi.fn() } }));
vi.mock("./notifications.api", () => ({ notificationsApi: {
  listDrafts: vi.fn(), createDraft: vi.fn(), updateDraft: vi.fn(), getDraft: vi.fn(), preview: vi.fn(),
  send: vi.fn(), byRequest: vi.fn(), listBatches: vi.fn(), getBatch: vi.fn(),
} }));
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear();
  vi.mocked(gcAppAdminApi.listGroups).mockResolvedValue({ items: [group], total: 1, page: 1, page_size: 20, has_next: false });
  vi.mocked(notificationsApi.listDrafts).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(notificationsApi.listBatches).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(notificationsApi.getBatch).mockResolvedValue(batch);
  vi.mocked(notificationsApi.createDraft).mockResolvedValue(draft);
  vi.mocked(notificationsApi.preview).mockResolvedValue(preview());
  vi.mocked(notificationsApi.send).mockResolvedValue(batch);
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client);
  render(<QueryClientProvider client={client}><NotificationsPage /></QueryClientProvider>);
}

describe("GC App Notifications operator workflow", () => {
  it("requires audience review and a separate explicit send, then shows honest provider status", async () => {
    setup(); const user = userEvent.setup();
    fireEvent.change(screen.getByLabelText(/Notification title/), { target: { value: draft.title } });
    fireEvent.change(screen.getByLabelText(/Notification message/), { target: { value: draft.body } });
    await user.click(await screen.findByRole("checkbox", { name: /Synthetic Hill Trip/ }));
    await user.click(screen.getByRole("button", { name: "Review audience" }));
    const dialog = await screen.findByRole("dialog", { name: "Review phone notification" });
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(within(dialog).getByLabelText("Phone alert preview")).toHaveTextContent(draft.body);
    await user.click(within(dialog).getByRole("button", { name: "Send notification" }));
    expect(await screen.findByRole("heading", { name: "Delivery summary" })).toBeVisible();
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Provider accepted; phone display unconfirmed/)).toBeVisible();
    expect(screen.getByText(/Unknown outcomes are not automatically resent/)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("recovers an earlier send after reload using read-only lookup and blocks new composition", async () => {
    persistPendingSend(pendingSendKey(agencyId, actorId), { request_id: batch.request_id, draft_id: draft.id });
    vi.mocked(notificationsApi.byRequest).mockResolvedValue(batch);
    setup(); const user = userEvent.setup();
    expect(screen.getByRole("heading", { name: "Check the previous send" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Review audience" })).toBeDisabled();
    expect(screen.getByLabelText(/Notification title/)).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Check recorded outcome" }));
    expect(await screen.findByRole("heading", { name: "Delivery summary" })).toBeVisible();
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review audience" })).toBeEnabled();
  });

  it("preparing a resend fills the editor and does not send or save automatically", async () => {
    vi.mocked(notificationsApi.listBatches).mockResolvedValue({ items: [batch], next_cursor: null });
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Prepare resend" }));
    expect(screen.getByLabelText(/Notification title/)).toHaveValue(batch.title);
    expect(screen.getByText(/recipients may receive the alert again/)).toBeVisible();
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
    expect(notificationsApi.preview).not.toHaveBeenCalled();
  });
});
