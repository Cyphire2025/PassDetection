import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  send: vi.fn(), byRequest: vi.fn(), listBatches: vi.fn(), getBatch: vi.fn(), deleteDraft: vi.fn(),
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
    await user.click(screen.getByRole("button", { name: "New notification" }));
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
    expect(screen.getByRole("button", { name: "New notification" })).toBeDisabled();
    expect(screen.queryByLabelText(/Notification title/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check recorded outcome" }));
    expect(await screen.findByRole("heading", { name: "Delivery summary" })).toBeVisible();
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "New notification" })).toBeEnabled();
  });

  it("preparing a resend fills the editor and does not send or save automatically", async () => {
    vi.mocked(notificationsApi.listDrafts).mockResolvedValue({ items: [{ ...draft, status: "sent", last_sent_at: batch.created_at }], next_cursor: null });
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Resend" }));
    expect(screen.getByLabelText(/Notification title/)).toHaveValue(draft.title);
    expect(screen.getByText(/Previous recipients may receive this alert again/)).toBeVisible();
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
    expect(notificationsApi.preview).not.toHaveBeenCalled();
  });

  it("opens History on its own route and keeps the main page focused on Saved", async () => {
    setup();
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute("href", "/gc-app/notifications/history");
    expect(screen.getByRole("heading", { name: "Saved notifications" })).toBeVisible();
    expect(notificationsApi.listBatches).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/Notification title/)).not.toBeInTheDocument();
  });

  it("saves an edited message from the dialog without sending and closes only after success", async () => {
    vi.mocked(notificationsApi.listDrafts).mockResolvedValue({ items: [draft], next_cursor: null });
    vi.mocked(notificationsApi.updateDraft).mockResolvedValue({ ...draft, body: "Updated message", revision: 2 });
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText(/Notification message/), { target: { value: "Updated message" } });
    await user.click(screen.getByRole("button", { name: "Save notification" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(notificationsApi.updateDraft).toHaveBeenCalledWith(agencyId, draft, expect.objectContaining({ body: "Updated message" }));
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(notificationsApi.preview).not.toHaveBeenCalled();
  });

  it("retains unsaved changes when Cancel is followed by Keep editing", async () => {
    setup(); const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New notification" }));
    fireEvent.change(screen.getByLabelText(/Notification title/), { target: { value: "Keep this message" } });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("dialog", { name: "Discard unsaved changes?" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByLabelText(/Notification title/)).toHaveValue("Keep this message");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
  });

  it("requires confirmation before removing Saved and preserves the failure for correction", async () => {
    vi.mocked(notificationsApi.listDrafts).mockResolvedValue({ items: [draft], next_cursor: null });
    vi.mocked(notificationsApi.deleteDraft).mockRejectedValueOnce({ status: 409, message: "draft_conflict" }).mockResolvedValueOnce(undefined);
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(notificationsApi.deleteDraft).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Delete saved notification?" });
    expect(within(dialog).getByText(/Its send history will stay in History/)).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Delete notification" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/changed/);
    expect(dialog).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Delete notification" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(notificationsApi.deleteDraft).toHaveBeenCalledWith(agencyId, draft);
    expect(notificationsApi.send).not.toHaveBeenCalled();
  });
});
