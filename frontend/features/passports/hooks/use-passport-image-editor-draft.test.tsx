import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePassportImageEditorDraft } from "./use-passport-image-editor-draft";
import { cropMetadata } from "./passport-image-editor.test-fixtures";

describe("passport image adjustment draft", () => {
  it("preserves fine rotation through quarter turns and restores the saved edit", () => {
    const setError = vi.fn();
    const { result } = renderHook(() => usePassportImageEditorDraft(cropMetadata, null, "adjust", { current: false }, setError));
    expect(result.current.cropRect).toEqual(cropMetadata.crop);
    act(() => { result.current.updateFineRotation(23); });
    expect(result.current.cropRect.rotation_degrees).toBe(113);
    act(() => { result.current.rotate("left"); result.current.setSharpness(2.5); });
    expect(result.current.cropRect.rotation_degrees).toBe(23);
    expect(result.current.fineRotation).toBe(23);
    expect(result.current.hasChanges).toBe(true);
    act(() => { result.current.undoChanges(); });
    expect(result.current.cropRect).toEqual(cropMetadata.crop);
    expect(result.current.sharpness).toBe(1.5);
    expect(result.current.hasChanges).toBe(false);
  });
});
