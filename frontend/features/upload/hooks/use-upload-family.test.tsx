import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUploadFamily } from "./use-upload-family";

describe("family state controller", () => {
  it("retains saved member identity through count edits, clamps selection, and normalizes an incomplete draft", () => {
    const { result } = renderHook(() => useUploadFamily());
    const firstKey = result.current.familyMembers[0].uploadIdempotencyKey;
    act(() => result.current.handleFamilyCountInput("3"));
    act(() => { result.current.setActiveFamilyIndex(2); result.current.updateFamilyMember(0, { name: "Saved member" }); });
    act(() => result.current.handleFamilyCountInput("2"));
    expect(result.current.activeFamilyIndex).toBe(1);
    expect(result.current.familyMembers[0]).toMatchObject({ name: "Saved member", uploadIdempotencyKey: firstKey });
    act(() => result.current.handleFamilyCountInput(""));
    expect(result.current.familyMembers).toHaveLength(2);
    expect(result.current.familyCountInput).toBe("");
    act(() => result.current.normalizeFamilyCountInput());
    expect(result.current.familyCountInput).toBe("2");
    act(() => result.current.handleFamilyCountInput("invalid"));
    expect(result.current.familyCountInput).toBe("2");
    act(() => result.current.handleFamilyCountInput("999999999999999999999999999999999999"));
    expect(result.current.familyMembers).toHaveLength(2);
  });
});
