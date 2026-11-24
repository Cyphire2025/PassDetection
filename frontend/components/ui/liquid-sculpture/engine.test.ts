import { afterEach, describe, expect, it, vi } from "vitest";
import { LiquidEngine } from "./engine";
import type { EngineOptions } from "./types";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("liquid sculpture initialization failure", () => {
  it("releases the GPU context when initialization fails before the owner receives the engine", () => {
    const loseContext = vi.fn();
    const getExtension = vi.fn((name: string) => name === "WEBGL_lose_context" ? { loseContext } : null);
    const canvas = document.createElement("canvas");
    vi.spyOn(canvas, "getContext").mockReturnValue({ getExtension } as unknown as WebGL2RenderingContext);
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
    expect(() => new LiquidEngine(canvas, {} as EngineOptions, vi.fn())).toThrow("No float render targets");
    expect(loseContext).toHaveBeenCalledOnce();
  });
});
