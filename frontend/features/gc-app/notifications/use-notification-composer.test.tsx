import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { notificationsApi } from "./notifications.api";
import { useNotificationComposer } from "./use-notification-composer";
import { agencyId, actorId, batch, draft, groupId, preview } from "./notification-test-fixtures";
import { pendingSendKey, persistPendingSend } from "./pending-send";

vi.mock("./notifications.api", () => ({ notificationsApi: {
  createDraft: vi.fn(), updateDraft: vi.fn(), preview: vi.fn(), send: vi.fn(),
  byRequest: vi.fn(), getDraft: vi.fn(), listDrafts: vi.fn(), listBatches: vi.fn(), getBatch: vi.fn(),
} }));
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(notificationsApi.createDraft).mockResolvedValue(draft);
  vi.mocked(notificationsApi.updateDraft).mockResolvedValue({ ...draft, revision: 2 });
  vi.mocked(notificationsApi.preview).mockResolvedValue(preview());
  vi.mocked(notificationsApi.getDraft).mockResolvedValue(draft);
  vi.mocked(notificationsApi.send).mockResolvedValue(batch);
  vi.mocked(notificationsApi.byRequest).mockRejectedValue({ status: 404 });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); });

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return renderHook(() => useNotificationComposer(agencyId, actorId), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}
const fill = (result: ReturnType<typeof setup>["result"]) => act(() => result.current.change({ title: draft.title, body: draft.body, audience: "selected_groups", group_ids: [groupId] }));

describe("Explicit notification composition and send recovery", () => {
  it("saving and reviewing create no phone send and reuse an unchanged saved draft", async () => {
    const { result } = setup(); fill(result);
    await act(() => result.current.save());
    await act(() => result.current.prepareReview());
    expect(notificationsApi.createDraft).toHaveBeenCalledTimes(1);
    expect(notificationsApi.updateDraft).not.toHaveBeenCalled();
    expect(notificationsApi.preview).toHaveBeenCalledExactlyOnceWith(agencyId, draft);
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
    expect(result.current.review?.preview.recipient_count).toBe(12);
  });

  it("does not accept empty text or an empty specific-group audience", async () => {
    const { result } = setup();
    await act(() => result.current.prepareReview());
    expect(result.current.error).toContain("title and message");
    act(() => result.current.change({ title: "Title", body: "Text", audience: "selected_groups", group_ids: [] }));
    await act(() => result.current.prepareReview());
    expect(result.current.error).toContain("at least one");
    expect(notificationsApi.createDraft).not.toHaveBeenCalled();
  });

  it("describes saving an unchanged previously sent message without denying its earlier send", async () => {
    const { result } = setup();
    act(() => result.current.edit({ ...draft, status: "sent", last_sent_at: batch.created_at }));
    await act(() => result.current.save());
    expect(result.current.notice).toBe("Message saved. This action did not send a phone notification.");
    expect(result.current.draft?.status).toBe("sent");
    expect(notificationsApi.updateDraft).not.toHaveBeenCalled();
    expect(notificationsApi.send).not.toHaveBeenCalled();
  });

  it("preserves failed draft edits and sends the saved revision on updates", async () => {
    const { result } = setup();
    act(() => result.current.edit(draft));
    act(() => result.current.change({ ...result.current.form, body: "Changed text" }));
    vi.mocked(notificationsApi.updateDraft).mockRejectedValue({ message: "draft_conflict", status: 409 });
    await act(() => result.current.prepareReview());
    expect(result.current.form.body).toBe("Changed text");
    expect(result.current.error).toContain("changed");
    expect(notificationsApi.updateDraft).toHaveBeenCalledWith(agencyId, draft, expect.objectContaining({ body: "Changed text" }));
    expect(notificationsApi.preview).not.toHaveBeenCalled();
  });

  it("writes an opaque recovery marker before HTTP and suppresses double-click sends", async () => {
    const { result } = setup(); fill(result);
    await act(() => result.current.prepareReview());
    let resolve!: (value: typeof batch) => void;
    vi.mocked(notificationsApi.send).mockImplementation((_agency, draftId, body) => {
      expect(JSON.parse(sessionStorage.getItem(pendingSendKey(agencyId, actorId))!)).toEqual({ draft_id: draftId, request_id: body.request_id });
      return new Promise((done) => { resolve = done; });
    });
    let sending!: Promise<void>;
    act(() => { sending = result.current.send(); void result.current.send(); });
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(batch); await sending; });
    expect(result.current.lastBatch?.id).toBe(batch.id);
    expect(result.current.pending).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  it("retains an ambiguous request across reload and resolves it with a read-only lookup", async () => {
    const first = setup(); fill(first.result);
    await act(() => first.result.current.prepareReview());
    vi.mocked(notificationsApi.send).mockRejectedValue({ code: "NETWORK_ERROR", message: "Response lost" });
    await act(() => first.result.current.send());
    const marker = first.result.current.pending!;
    expect(marker.request_id).toBeTruthy();
    expect(first.result.current.error).toContain("Check this send");
    act(() => first.result.current.change({ title: "New text", body: "Another send", audience: "all_active_trips", group_ids: [] }));
    expect(first.result.current.form.title).toBe(draft.title);
    first.unmount();
    const second = setup();
    expect(second.result.current.pending).toEqual(marker);
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
    vi.mocked(notificationsApi.byRequest).mockResolvedValue({ ...batch, request_id: marker.request_id });
    await act(() => second.result.current.checkPending());
    expect(notificationsApi.byRequest).toHaveBeenCalledWith(agencyId, marker.request_id);
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
    expect(second.result.current.pending).toBeNull();
  });

  it("refreshes review but reuses the original request UUID when a missing send is retried", async () => {
    persistPendingSend(pendingSendKey(agencyId, actorId), { request_id: batch.request_id, draft_id: draft.id });
    const { result } = setup();
    await act(() => result.current.reviewPending());
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(result.current.review?.draft.title).toBe(draft.title);
    await act(() => result.current.retryPending());
    expect(notificationsApi.send).toHaveBeenCalledExactlyOnceWith(agencyId, draft.id, {
      request_id: batch.request_id, expected_revision: 1, preview_token: "synthetic-preview-token",
    });
  });

  it("unlocks the saved message after a selected trip is paused between review and send", async () => {
    const { result } = setup(); fill(result);
    await act(() => result.current.prepareReview());
    vi.mocked(notificationsApi.send).mockRejectedValue({ status: 409, message: "audience_changed" });
    await act(() => result.current.send());
    expect(result.current.pending).toBeNull();
    expect(sessionStorage.length).toBe(0);
    expect(result.current.review).toBeNull();
    expect(result.current.form.title).toBe(draft.title);
    expect(result.current.form.body).toBe(draft.body);
    expect(result.current.error).toContain("availability or recipient access has changed");
    act(() => result.current.change({ ...result.current.form, audience: "all_active_trips", group_ids: [] }));
    expect(result.current.form.audience).toBe("all_active_trips");
    expect(result.current.form.group_ids).toEqual([]);
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
  });

  it.each([
    { status: 503, message: "Temporarily unavailable" },
    { status: 409, message: "idempotency_conflict" },
    { status: 409, message: "stale_preview" },
    { status: 500, message: "audience_changed" },
  ])("retains the original send reference for an unconfirmed $status/$message outcome", async (error) => {
    const { result } = setup(); fill(result);
    await act(() => result.current.prepareReview());
    vi.mocked(notificationsApi.send).mockRejectedValue(error);
    await act(() => result.current.send());
    expect(result.current.pending?.request_id).toBeTruthy();
    expect(sessionStorage.getItem(pendingSendKey(agencyId, actorId))).not.toBeNull();
    act(() => result.current.change({ ...result.current.form, title: "Do not replace the unresolved send" }));
    expect(result.current.form.title).toBe(draft.title);
    expect(notificationsApi.send).toHaveBeenCalledTimes(1);
  });

  it("unlocks a retry only after the server confirms no send exists and rejects its new audience", async () => {
    persistPendingSend(pendingSendKey(agencyId, actorId), { request_id: batch.request_id, draft_id: draft.id });
    const { result } = setup();
    await act(() => result.current.reviewPending());
    vi.mocked(notificationsApi.send).mockRejectedValue({ status: 409, message: "no_eligible_recipients" });
    await act(() => result.current.retryPending());
    expect(result.current.pending).toBeNull();
    expect(result.current.form.body).toBe(draft.body);
    expect(result.current.notice).toContain("before recording a send");
    expect(notificationsApi.send).toHaveBeenCalledExactlyOnceWith(agencyId, draft.id, expect.objectContaining({ request_id: batch.request_id }));
  });

  it("preparing a deliberate resend sends nothing until reviewed and uses a fresh UUID", async () => {
    const { result } = setup();
    act(() => result.current.resend({ ...batch, audience: "all_active_trips" }));
    expect(result.current.form.group_ids).toEqual([]);
    expect(result.current.resending).toBe(true);
    expect(notificationsApi.send).not.toHaveBeenCalled();
    vi.mocked(notificationsApi.createDraft).mockResolvedValue({ ...draft, audience: "all_active_trips", group_ids: [] });
    await act(() => result.current.prepareReview());
    expect(notificationsApi.createDraft).toHaveBeenCalledWith(agencyId, expect.objectContaining({ audience: "all_active_trips", group_ids: [] }));
    await act(() => result.current.send());
    expect(vi.mocked(notificationsApi.send).mock.calls[0]?.[2].request_id).not.toBe(batch.request_id);
  });

  it("does not send if the recovery marker cannot be stored", async () => {
    const { result } = setup(); fill(result);
    await act(() => result.current.prepareReview());
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    await act(() => result.current.send());
    expect(notificationsApi.send).not.toHaveBeenCalled();
    expect(result.current.error).toContain("session storage");
  });
});
