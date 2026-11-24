import { afterEach, expect, it, vi } from "vitest";
import { validatePassportFinalFile } from "./passport-final-quality";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const file = () => new File(["synthetic encoded JPEG"], "passport.jpg", { type: "image/jpeg" });

it("validates the supplied encoded file and releases its bitmap even when the canvas is unavailable", async () => {
  const close = vi.fn();
  const decode = vi.fn().mockResolvedValue({ width: 1440, height: 990, close });
  vi.stubGlobal("createImageBitmap", decode);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  const outgoing = file();
  const result = await validatePassportFinalFile(outgoing, "front");
  expect(decode).toHaveBeenCalledExactlyOnceWith(outgoing);
  expect(result).toMatchObject({ outcome: "hard_failure", reason: "invalid_image", metrics: { sourceWidth: 1440, sourceHeight: 990 } });
  expect(close).toHaveBeenCalledOnce();
});

it("releases the decoded bitmap after a canvas read failure", async () => {
  const close = vi.fn();
  vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 1440, height: 990, close }));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), getImageData: () => { throw new Error("Synthetic canvas failure"); } } as unknown as CanvasRenderingContext2D);
  await expect(validatePassportFinalFile(file(), "back")).rejects.toThrow("Synthetic canvas failure");
  expect(close).toHaveBeenCalledOnce();
});

it("closes the decoded bitmap after analyzing the exact encoded pixels", async () => {
  const close = vi.fn();
  vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 120, height: 80, close }));
  const pixels = new Uint8ClampedArray(120 * 80 * 4).fill(8);
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage, getImageData: () => ({ data: pixels }) } as unknown as CanvasRenderingContext2D);
  const result = await validatePassportFinalFile(file(), "front");
  expect(result).toMatchObject({ outcome: "hard_failure", reason: "extreme_exposure" });
  expect(drawImage).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledOnce();
});

it.each(["load", "error"])("revokes the HTML image fallback URL after %s", async outcome => {
  vi.stubGlobal("createImageBitmap", undefined);
  vi.stubGlobal("Image", class {
    naturalWidth = 1440;
    naturalHeight = 990;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(_value: string) { queueMicrotask(() => outcome === "load" ? this.onload?.() : this.onerror?.()); }
  });
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic-final-quality");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  const outgoing = file();
  if (outcome === "load") await expect(validatePassportFinalFile(outgoing, "front")).resolves.toMatchObject({ reason: "invalid_image" });
  else await expect(validatePassportFinalFile(outgoing, "front")).rejects.toThrow("could not be decoded");
  expect(create).toHaveBeenCalledExactlyOnceWith(outgoing);
  expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:synthetic-final-quality");
});
