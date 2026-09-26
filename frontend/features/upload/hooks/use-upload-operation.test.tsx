import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUploadOperation, type UploadOperation } from "./use-upload-operation";

describe("upload operation ownership", () => {
  it("admits only one upload even before React commits a render", () => {
    const { result } = renderHook(() => useUploadOperation());
    act(() => {
      expect(result.current.begin("upload")).not.toBeNull();
      expect(result.current.begin("upload")).toBeNull();
      expect(result.current.begin("submit")).toBeNull();
    });
    expect(result.current.state).toMatchObject({ status: "active", kind: "upload" });
  });
  it("cancels the old request and prevents its finally handler from unlocking a retry", () => {
    const { result } = renderHook(() => useUploadOperation());
    let old!: UploadOperation;
    act(() => { old = result.current.begin("upload")!; });
    act(() => result.current.cancel());
    let retry!: UploadOperation;
    act(() => { retry = result.current.begin("retry")!; });
    act(() => result.current.finish(old));
    expect(old.controller.signal.aborted).toBe(true);
    expect(result.current.isCurrent(old)).toBe(false);
    expect(result.current.isCurrent(retry)).toBe(true);
    expect(result.current.isBusy()).toBe(true);
    expect(result.current.state).toMatchObject({ status: "active", kind: "retry" });
  });
  it("rejects results after unmount and aborts their network signal", () => {
    const { result, unmount } = renderHook(() => useUploadOperation());
    let pending!: UploadOperation;
    act(() => { pending = result.current.begin("submit")!; });
    unmount();
    expect(pending.controller.signal.aborted).toBe(true);
    expect(result.current.isCurrent(pending)).toBe(false);
    expect(result.current.begin("replace")).toBeNull();
  });
  it("fences a previous public link's promise when the token changes", () => {
    const { result, rerender } = renderHook(({ token }) => useUploadOperation(token), { initialProps: { token: "old" } });
    let pending!: UploadOperation;
    act(() => { pending = result.current.begin("resume")!; });
    rerender({ token: "new" });
    expect(result.current.isCurrent(pending)).toBe(false);
    expect(result.current.isBusy()).toBe(false);
    expect(result.current.state.status).toBe("idle");
  });
});
