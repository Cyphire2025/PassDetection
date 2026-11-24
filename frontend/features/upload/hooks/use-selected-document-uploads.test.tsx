import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { preparePublicUploadFile } from "../services/public-upload-file";
import { useSelectedDocumentUploads } from "./use-selected-document-uploads";

vi.mock("../services/public-upload-file", () => ({ preparePublicUploadFile: vi.fn() }));
const file = () => new File(["synthetic-camera-bytes"], "passport.jpg", { type: "image/jpeg" });
function inputs(): DraftDocumentInputs {
  return { pending: false, payload: undefined, draft: { documents: [] }, collection: vi.fn(), upload: vi.fn().mockResolvedValue({ documents: [] }), api: { document: vi.fn() } };
}
beforeEach(() => vi.resetAllMocks());

describe("active private document acquisition", () => {
  it("keeps validated camera bytes unchanged and binds photo provenance", async () => {
    const state = inputs(), original = file();
    const hook = renderHook(() => useSelectedDocumentUploads(state, "trip", "member"));
    await act(() => hook.result.current.upload("photo", original, "camera"));
    expect(preparePublicUploadFile).not.toHaveBeenCalled();
    expect(state.upload).toHaveBeenCalledExactlyOnceWith("photo", original);
    expect(state.collection).toHaveBeenCalledExactlyOnceWith({ visa_photo_source: "camera" });
  });

  it("admits one transfer and aborts pending private preparation on page exit", async () => {
    const state = inputs(); let finish!: (value: File) => void;
    vi.mocked(preparePublicUploadFile).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(() => useSelectedDocumentUploads(state, "trip", "private-member"));
    let pending!: Promise<void>;
    act(() => { pending = hook.result.current.upload("front", file(), "file"); void hook.result.current.upload("back", file(), "file"); });
    expect(preparePublicUploadFile).toHaveBeenCalledOnce();
    const options = vi.mocked(preparePublicUploadFile).mock.calls[0][1]!;
    expect(options).toMatchObject({ token: "trip", uploadSessionId: "private-member", purpose: "passport" });
    await act(async () => window.dispatchEvent(new Event("pagehide")));
    expect(options.signal?.aborted).toBe(true);
    await act(async () => { finish(file()); await pending; });
    expect(state.upload).not.toHaveBeenCalled(); expect(state.collection).not.toHaveBeenCalled();
    expect(hook.result.current.selected).toEqual({}); expect(hook.result.current.pendingSide).toBeUndefined();
  });

  it("hides selected bytes once another authoritative asset replaces that side", async () => {
    const original = file(), state = inputs();
    vi.mocked(state.upload).mockResolvedValue({ documents: [{ id: "accepted", side: "front", state: "ready" }] });
    state.draft = { documents: [{ id: "accepted", side: "front", state: "ready" }] };
    const hook = renderHook(({ value }) => useSelectedDocumentUploads(value, "trip", "member"), { initialProps: { value: state } });
    await act(() => hook.result.current.upload("front", original, "camera"));
    expect(hook.result.current.selected.front).toBe(original);
    hook.rerender({ value: { ...state, draft: { documents: [{ id: "new-authority", side: "front", state: "ready" }] } } });
    await waitFor(() => expect(hook.result.current.selected).toEqual({}));
  });
});
