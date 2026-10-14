import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FreshDraft, FreshPayload } from "../api/fresh-draft.api";
import { useFreshDraft } from "./use-fresh-draft";

const api = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), complete: vi.fn() }));
vi.mock("../api/fresh-draft.api", () => ({ freshDraftApi: () => api }));
const collection = { acquisition_mode: "file" as const, submission_mode: "single" as const };
const member = { sessionId: "private-member", submissionKey: "stable-final-key", completed: false };
let server: FreshDraft;
const snapshot = () => structuredClone(server);
beforeEach(() => {
  vi.clearAllMocks();
  server = { id: "draft", revision: 1, expires_at: "2099-01-01", status: "active", verified_phone: null, collection, passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, documents: [], extracted_fields: {}, extraction_status: "none" };
  api.start.mockImplementation(async () => snapshot()); api.read.mockImplementation(async () => snapshot());
  api.save.mockImplementation(async (payload: FreshPayload, revision: number) => { expect(revision).toBe(server.revision); server = { ...server, ...payload, revision: revision + 1 }; return snapshot(); });
  api.upload.mockImplementation(async () => { server = { ...server, revision: server.revision + 1, passport_fields: { given_names: "EXTRACTED" } }; return snapshot(); });
  api.complete.mockImplementation(async () => { server.status = "submitted"; return { source_submission_id: "source", status: "submitted" }; });
});
async function ready() {
  const hook = renderHook(() => useFreshDraft("trip", member, collection));
  await waitFor(() => expect(hook.result.current.pending).toBe(false)); return hook;
}
describe("fresh private draft revision stream", () => {
  it("saves edits before uploads and submits once with the persistent member key", async () => {
    const { result } = await ready();
    act(() => result.current.update("current_details", "staff_code", "STAFF"));
    await act(() => result.current.upload("front", new File(["synthetic"], "passport.jpg", { type: "image/jpeg" })));
    expect(api.save).toHaveBeenCalledTimes(1); expect(api.upload.mock.calls[0][2]).toBe(2);
    expect(result.current.payload?.current_details.staff_code).toBe("STAFF"); expect(result.current.payload?.passport_fields.given_names).toBe("EXTRACTED");
    expect(api.complete).not.toHaveBeenCalled();
    await act(() => result.current.complete("verified-proof"));
    expect(api.complete.mock.calls[0].slice(0, 3)).toEqual([3, "verified-proof", "stable-final-key"]);
    expect(result.current.draft?.status).toBe("submitted");
  });
  it("preserves an edit typed while a save response arrives", async () => {
    const { result } = await ready(); let resolve!: (value: FreshDraft) => void;
    api.save.mockImplementationOnce(() => new Promise<FreshDraft>((done) => { resolve = done; }));
    act(() => result.current.update("current_details", "client_email", "first@example.test"));
    let pending!: Promise<void>; act(() => { pending = result.current.flush(); });
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    act(() => result.current.update("current_details", "client_email", "latest@example.test"));
    server = { ...server, revision: 2, current_details: { client_email: "first@example.test" }, passport_fields: { given_names: "AUTOMATIC" } };
    await act(async () => { resolve(snapshot()); await pending; });
    expect(result.current.payload?.current_details.client_email).toBe("latest@example.test");
    expect(result.current.payload?.passport_fields.given_names).toBe("AUTOMATIC");
    await act(() => result.current.flush()); expect(server.current_details.client_email).toBe("latest@example.test");
  });
  it("reuses the same save and final keys after uncertain network failures", async () => {
    const { result } = await ready(); api.save.mockRejectedValueOnce(new Error("Network unavailable"));
    act(() => result.current.update("current_details", "client_name", "Synthetic"));
    await act(async () => { await expect(result.current.flush()).rejects.toThrow("Network unavailable"); });
    await act(() => result.current.flush()); expect(api.save.mock.calls[0][2]).toBe(api.save.mock.calls[1][2]);
    api.complete.mockRejectedValueOnce(new Error("Connection interrupted"));
    await act(async () => { await expect(result.current.complete("proof")).rejects.toThrow("Connection interrupted"); });
    await act(() => result.current.complete("proof")); expect(api.complete.mock.calls[0][2]).toBe(api.complete.mock.calls[1][2]);
  });
  it("cancels member requests when navigation replaces the member", async () => {
    const { unmount } = await ready(); const signal = api.start.mock.calls[0][0] as AbortSignal;
    expect(signal.aborted).toBe(false); unmount(); expect(signal.aborted).toBe(true);
  });
  it("keeps an uncertain upload key, then discards it after a definitive revision conflict", async () => {
    const { result } = await ready(); const file = new File(["synthetic"], "passport.jpg", { type: "image/jpeg", lastModified: 100 });
    api.upload.mockRejectedValueOnce(new Error("Network unavailable"));
    await act(async () => { await expect(result.current.upload("front", file)).rejects.toThrow("Network unavailable"); });
    api.upload.mockRejectedValueOnce({ status: 409 });
    await act(async () => { await expect(result.current.upload("front", file)).rejects.toThrow("Review the latest details"); });
    expect(api.upload.mock.calls[0][3]).toBe(api.upload.mock.calls[1][3]);
    await act(() => result.current.upload("front", file)); expect(api.upload.mock.calls[2][3]).not.toBe(api.upload.mock.calls[1][3]);
  });
  it("flushes the last dirty edit when the page becomes hidden", async () => {
    const { result } = await ready(); const visibility = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => result.current.update("current_details", "client_name", "Last typed value"));
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(server.current_details.client_name).toBe("Last typed value"));
    visibility.mockRestore();
  });
});
