import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { returningDraftApi, type ReturningDraft } from "../api/returning-draft.api";
import { useReturningDraft } from "./use-returning-draft";
import type { ReturningHistory } from "../types";

vi.mock("../api/returning-draft.api", () => ({ returningDraftApi: { start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), complete: vi.fn() } }));
const history = { review_version: "review", question_version: "questions", participation_revision: null } as ReturningHistory;
let state: ReturningDraft;
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  state = { id: "draft", revision: 1, expires_at: new Date(Date.now() + 86400000).toISOString(), status: "active", passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, verified_phone: null, documents: [], extraction_status: "none", extracted_fields: {} };
  vi.mocked(returningDraftApi.start).mockResolvedValue(state);
  vi.mocked(returningDraftApi.read).mockImplementation(async () => state);
  vi.mocked(returningDraftApi.save).mockImplementation(async (payload) => { state = { ...state, ...payload, revision: state.revision + 1 }; return state; });
});
async function setup() {
  const hook = renderHook(() => useReturningDraft(history, "synthetic-group"));
  await waitFor(() => expect(hook.result.current.draft).toBeDefined()); return hook;
}
describe("returning autosave revisions", () => {
  it("retries an uncertain save with its original operation, then saves the newer edit", async () => {
    const hook = await setup();
    vi.mocked(returningDraftApi.save).mockRejectedValueOnce(new Error("Connection interrupted"));
    act(() => hook.result.current.update("current_details", "staff_code", "001"));
    await act(async () => { await hook.result.current.flush().catch(() => undefined); });
    act(() => hook.result.current.update("current_details", "staff_code", "002"));
    await act(async () => { await hook.result.current.flush(); });
    const calls = vi.mocked(returningDraftApi.save).mock.calls;
    expect(calls[0].slice(0, 3)).toEqual(calls[1].slice(0, 3));
    expect(hook.result.current.payload?.current_details.staff_code).toBe("002");
    expect(hook.result.current.dirty).toBe(true);
    await act(async () => { await hook.result.current.flush(); });
    expect(state.current_details.staff_code).toBe("002"); expect(hook.result.current.dirty).toBe(false);
  });
  it("rebases against background OCR and retains typed current-trip answers", async () => {
    const hook = await setup();
    state = { ...state, revision: 2, passport_fields: { given_names: "SYNTHETIC" } };
    vi.mocked(returningDraftApi.save).mockRejectedValueOnce({ status: 409 });
    act(() => hook.result.current.update("custom_answers", "meal", "Jain"));
    await act(async () => { await hook.result.current.flush(); });
    expect(hook.result.current.payload).toMatchObject({ passport_fields: { given_names: "SYNTHETIC" }, custom_answers: { meal: "Jain" } });
    expect(vi.mocked(returningDraftApi.save).mock.calls[1][1]).toBe(2);
  });
  it("retains staged photo and qualifier metadata across an OCR revision conflict", async () => {
    const hook = await setup();
    state = { ...state, revision: 2, passport_fields: { given_names: "SYNTHETIC" } };
    vi.mocked(returningDraftApi.save).mockRejectedValueOnce({ status: 409 });
    act(() => { hook.result.current.collection({ visa_photo_source: "camera" }); hook.result.current.collection({ qualifier_selection_token: "selection" }); });
    await act(async () => { await hook.result.current.flush(); });
    expect(state.collection).toMatchObject({ visa_photo_source: "camera", qualifier_selection_token: "selection" });
    expect(hook.result.current.payload?.passport_fields.given_names).toBe("SYNTHETIC");
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
  });
  it("refuses completion when an unsaved edit arrives during the save", async () => {
    const hook = await setup(); let finish!: (value: ReturningDraft) => void;
    vi.mocked(returningDraftApi.save).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    act(() => hook.result.current.update("custom_answers", "meal", "Veg"));
    let completion: Promise<unknown>;
    act(() => { completion = hook.result.current.complete().catch((cause: Error) => cause.message); });
    await waitFor(() => expect(returningDraftApi.save).toHaveBeenCalled());
    act(() => hook.result.current.update("custom_answers", "meal", "Jain"));
    await act(async () => { finish({ ...state, revision: 2, custom_answers: { meal: "Veg" } }); expect(await completion!).toContain("latest edit"); });
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    expect(hook.result.current.payload?.custom_answers.meal).toBe("Jain");
  });
  it("does not revive an expired or replaced draft during a conflict", async () => {
    const hook = await setup();
    vi.mocked(returningDraftApi.save).mockRejectedValueOnce({ status: 409, message: "Draft expired" });
    vi.mocked(returningDraftApi.read).mockResolvedValue({ ...state, id: "another-draft" });
    act(() => hook.result.current.update("custom_answers", "meal", "Jain"));
    await act(async () => { await hook.result.current.flush().catch(() => undefined); });
    expect(returningDraftApi.save).toHaveBeenCalledOnce(); expect(hook.result.current.error).toBe("Draft expired");
  });
});
