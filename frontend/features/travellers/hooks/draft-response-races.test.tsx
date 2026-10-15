import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useFreshDraft } from "@/features/upload/hooks/use-fresh-draft";
import { useReturningDraft } from "./use-returning-draft";
import type { FreshDraft, FreshPayload } from "@/features/upload/api/fresh-draft.api";
import type { ReturningHistory } from "../types";
import type { ReturningDraft } from "../api/draft.types";

const fresh = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), complete: vi.fn(), activity: vi.fn(), discard: vi.fn() }));
const returning = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), complete: vi.fn(), activity: vi.fn(), discard: vi.fn() }));
vi.mock("@/features/upload/api/fresh-draft.api", () => ({ freshDraftApi: () => fresh }));
vi.mock("../api/returning-draft.api", () => ({ returningDraftApi: returning }));
const collection = { acquisition_mode: "file" as const, submission_mode: "single" as const };
const member = { sessionId: "member", submissionKey: "submit", completed: false };
const history = { review_version: "review", question_version: "questions" } as ReturningHistory;
let server: FreshDraft;
const snapshot = () => structuredClone(server);
const file = (content = "synthetic") => new File([content], "passport.jpg", { type: "image/jpeg", lastModified: 100 });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };
afterEach(() => vi.useRealTimers());

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  server = { id: "draft", revision: 1, expires_at: "2099-01-01", status: "active", verified_phone: null, collection, passport_fields: { given_names: "OLD" }, current_details: {}, custom_answers: {}, custom_detail_answers: {}, documents: [], extracted_fields: {}, extraction_status: "none" };
  for (const api of [fresh, returning]) {
    api.start.mockImplementation(async () => snapshot()); api.read.mockImplementation(async () => snapshot());
    api.save.mockImplementation(async (payload: FreshPayload, revision: number) => { expect(revision).toBe(server.revision); server = { ...server, ...payload, revision: revision + 1 }; return snapshot(); });
    api.upload.mockImplementation(async () => { server = { ...server, revision: server.revision + 1, passport_fields: { given_names: "EXTRACTED" } }; return snapshot(); });
    api.activity.mockResolvedValue({ images_present: true, presence_recorded: true, heartbeat_after_seconds: 60 });
    api.discard.mockImplementation(async () => { server = { ...server, revision: server.revision + 1, documents: [], extraction_status: "none" }; return snapshot(); });
  }
});

for (const kind of ["fresh", "returning"] as const) {
  const api = kind === "fresh" ? fresh : returning;
  type Subject = Pick<ReturnType<typeof useReturningDraft>, "pending" | "payload" | "update" | "flush" | "refresh" | "upload" | "leave"> & { draft?: FreshDraft | ReturningDraft };
  const useSubject: () => Subject = kind === "fresh" ? () => useFreshDraft("trip", member, collection) : () => useReturningDraft(history, "trip");
  async function setup() { const hook = renderHook(useSubject); await waitFor(() => expect(hook.result.current.pending).toBe(false)); return hook; }
  describe(`${kind} draft response races`, () => {
    it("automatically polls an uploaded passport until extracted fields arrive and then stops", async () => {
      const hook = await setup();
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
      api.upload.mockImplementationOnce(async () => {
        server = { ...server, revision: 3, passport_fields: {},
          documents: [{ id: "selected-front", side: "front", state: "ready" }], extraction_status: "pending" };
        return snapshot();
      });
      await act(() => hook.result.current.upload("front", file()));
      expect(hook.result.current.draft?.extraction_status).toBe("pending");
      expect(hook.result.current.payload?.passport_fields).toEqual({});
      act(() => hook.result.current.update("custom_answers", "meal", "Veg"));
      server = { ...server, extraction_status: "running" };
      await act(() => vi.advanceTimersByTimeAsync(2_000));
      expect(api.read).toHaveBeenCalledOnce();
      expect(hook.result.current.draft?.extraction_status).toBe("running");
      const fields = { given_names: "SYNTHETIC", surname: "TRAVELLER", passport_number: "TEST1234",
        nationality: "Indian", place_of_issue: "TEST CITY", date_of_birth: "1990-01-01",
        date_of_issue: "2024-01-01", date_of_expiry: "2034-01-01", sex: "F" };
      server = { ...server, revision: server.revision + 1, extraction_status: "succeeded",
        passport_fields: fields, extracted_fields: fields };
      await act(() => vi.advanceTimersByTimeAsync(2_000));
      expect(api.read).toHaveBeenCalledTimes(2);
      expect(hook.result.current.draft?.extraction_status).toBe("succeeded");
      expect(hook.result.current.payload?.passport_fields).toEqual(fields);
      expect(hook.result.current.payload?.custom_answers.meal).toBe("Veg");
      expect(hook.result.current.draft?.documents[0].id).toBe("selected-front");
      await act(() => vi.advanceTimersByTimeAsync(10_000));
      expect(api.read).toHaveBeenCalledTimes(2);
      hook.unmount();
    });

    it("saves the latest text before explicitly leaving and removes only temporary images", async () => {
      server.documents = [{ id: "staged-front", side: "front", state: "ready" }];
      const hook = await setup(); act(() => hook.result.current.update("current_details", "staff_code", "KEEP THIS"));
      await act(() => hook.result.current.leave());
      expect(api.save).toHaveBeenCalledOnce(); expect(api.discard.mock.calls[0][0]).toBe(2);
      expect(hook.result.current.draft?.documents).toEqual([]); expect(hook.result.current.payload?.current_details.staff_code).toBe("KEEP THIS");
      expect(server.passport_fields.given_names).toBe("OLD");
    });

    it("cancels an upload on pagehide and cannot restore its late response", async () => {
      const hook = await setup(), response = deferred<FreshDraft>(); api.upload.mockReturnValueOnce(response.promise);
      let request!: Promise<unknown>; act(() => { request = hook.result.current.upload("front", file()); });
      await waitFor(() => expect(api.upload).toHaveBeenCalledOnce());
      const signal = api.upload.mock.calls[0][kind === "fresh" ? 4 : 5] as AbortSignal;
      const late = { ...snapshot(), revision: 3, documents: [{ id: "late-front", side: "front" as const, state: "ready" as const }] };
      await act(async () => window.dispatchEvent(new Event("pagehide")));
      expect(signal.aborted).toBe(true); expect(api.discard.mock.calls[0][0]).toBe(1);
      await act(async () => { response.resolve(late); await request; });
      expect(hook.result.current.draft?.documents).toEqual([]); expect(api.upload).toHaveBeenCalledOnce();
    });

    it("adopts new extraction while keeping a detail typed during a read, including the next save", async () => {
      const hook = await setup(), response = deferred<FreshDraft>(); api.read.mockReturnValueOnce(response.promise);
      let request!: Promise<void>; act(() => { request = hook.result.current.refresh(); });
      await waitFor(() => expect(api.read).toHaveBeenCalledOnce());
      act(() => hook.result.current.update("current_details", "staff_code", "LATEST"));
      server = { ...server, revision: 2, passport_fields: { given_names: "NEW OCR", passport_number: "P123" } };
      await act(async () => { response.resolve(snapshot()); await request; });
      expect(hook.result.current.payload).toMatchObject({ passport_fields: server.passport_fields, current_details: { staff_code: "LATEST" } });
      await act(() => hook.result.current.flush());
      expect(server.passport_fields.given_names).toBe("NEW OCR"); expect(server.current_details.staff_code).toBe("LATEST");
    });

    it("preserves a typed passport correction and unrelated extraction from a pending upload", async () => {
      const hook = await setup(), response = deferred<FreshDraft>(); api.upload.mockReturnValueOnce(response.promise);
      let request!: Promise<unknown>; act(() => { request = hook.result.current.upload("front", file()); });
      await waitFor(() => expect(api.upload).toHaveBeenCalledOnce());
      act(() => { hook.result.current.update("passport_fields", "given_names", "MY CORRECTION"); hook.result.current.update("custom_answers", "meal", "Jain"); });
      server = { ...server, revision: 2, passport_fields: { given_names: "OCR NAME", passport_number: "P456" }, documents: [{ id: "new-front", side: "front", state: "ready" }] };
      await act(async () => { response.resolve(snapshot()); await request; });
      expect(hook.result.current.payload).toMatchObject({ passport_fields: { given_names: "MY CORRECTION", passport_number: "P456" }, custom_answers: { meal: "Jain" } });
      await act(() => hook.result.current.flush()); expect(server.passport_fields.given_names).toBe("MY CORRECTION");
      expect(server.passport_fields.passport_number).toBe("P456"); expect(hook.result.current.draft?.documents[0].id).toBe("new-front");
    });

    it("recovers one unrelated background revision without asking for a second image selection", async () => {
      server.documents = [{ id: "previous-front", side: "front", state: "ready" }];
      const hook = await setup();
      api.upload.mockImplementationOnce(async () => { server = { ...server, revision: 2, passport_fields: { given_names: "BACKGROUND" } }; throw { status: 409 }; });
      await act(() => hook.result.current.upload("front", file()));
      expect(api.upload).toHaveBeenCalledTimes(2); expect(api.read).toHaveBeenCalledOnce();
      expect(api.upload.mock.calls.map((call) => call[2])).toEqual([1, 2]);
      expect(api.upload.mock.calls[0][3]).not.toBe(api.upload.mock.calls[1][3]);
      expect(api.upload.mock.calls[1][kind === "fresh" ? 5 : 6]).toBe("previous-front");
      expect(hook.result.current.payload?.passport_fields.given_names).toBe("EXTRACTED");
    });

    it("does not overwrite a different image uploaded in another window", async () => {
      const hook = await setup();
      api.upload.mockImplementationOnce(async () => { server = { ...server, revision: 2, documents: [{ id: "other-window", side: "front", state: "ready" }] }; throw { status: 409 }; });
      await act(async () => { await expect(hook.result.current.upload("front", file())).rejects.toThrow("another window"); });
      expect(api.upload).toHaveBeenCalledOnce(); expect(hook.result.current.draft?.documents[0].id).toBe("other-window");
    });

    it("does not loop if the one safe upload retry also conflicts", async () => {
      const hook = await setup();
      api.upload.mockImplementation(async () => { server = { ...server, revision: server.revision + 1 }; throw { status: 409 }; });
      await act(async () => { await expect(hook.result.current.upload("front", file())).rejects.toMatchObject({ status: 409 }); });
      expect(api.upload).toHaveBeenCalledTimes(2); expect(api.read).toHaveBeenCalledOnce();
    });

    it("reuses uncertain upload identity for identical bytes, but not equal-name different bytes", async () => {
      const hook = await setup(); api.upload.mockRejectedValue(new Error("Connection interrupted"));
      for (const image of [file("one"), file("one"), file("two")]) {
        await act(async () => { await expect(hook.result.current.upload("front", image)).rejects.toThrow("Connection interrupted"); });
      }
      expect(api.upload.mock.calls[0][3]).toBe(api.upload.mock.calls[1][3]);
      expect(api.upload.mock.calls[1][3]).not.toBe(api.upload.mock.calls[2][3]);
    });

    it("does not adopt a read older than the acknowledged draft revision", async () => {
      const hook = await setup(), stale = snapshot();
      act(() => hook.result.current.update("current_details", "staff_code", "CURRENT"));
      await act(() => hook.result.current.flush()); api.read.mockResolvedValueOnce(stale);
      await act(() => hook.result.current.refresh());
      expect(hook.result.current.draft?.revision).toBe(2); expect(hook.result.current.payload?.current_details.staff_code).toBe("CURRENT");
    });

    it("still rejects conflicting edits from another window during a save", async () => {
      const hook = await setup();
      act(() => hook.result.current.update("passport_fields", "given_names", "LOCAL"));
      server = { ...server, revision: 2, passport_fields: { given_names: "OTHER WINDOW" } }; api.save.mockRejectedValueOnce({ status: 409 });
      await act(async () => { await expect(hook.result.current.flush()).rejects.toThrow("another window"); });
      expect(api.save).toHaveBeenCalledOnce(); expect(server.passport_fields.given_names).toBe("OTHER WINDOW");
      expect(hook.result.current.payload?.passport_fields.given_names).toBe("LOCAL");
    });
  });
}
