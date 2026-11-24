import { afterEach, describe, expect, it, vi } from "vitest";
import { createExportRequestId } from "../components/passport-group-feedback";
import { createRosterRequestId } from "../components/group-whatsapp-tracking-model";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe.each([
  ["export", createExportRequestId], ["roster", createRosterRequestId],
] as const)("%s retry request IDs", (_name, createId) => {
  it("uses the browser UUID implementation when available", () => {
    const randomUUID = vi.fn(() => "33c23cf4-c8f9-42ef-b147-337e5baa8331");
    vi.stubGlobal("crypto", { randomUUID });
    expect(createId()).toBe("33c23cf4-c8f9-42ef-b147-337e5baa8331");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("preserves UUID version and variant bits in the random-byte fallback", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => bytes.fill(255));
    vi.stubGlobal("crypto", { getRandomValues });
    expect(createId()).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(getRandomValues).toHaveBeenCalledOnce();
  });

  it("preserves the existing compatibility fallback when browser crypto is absent", () => {
    vi.stubGlobal("crypto", undefined);
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    expect(createId()).toBe("00000000-0000-4000-8000-000000000000");
    expect(random).toHaveBeenCalledTimes(16);
  });
});
