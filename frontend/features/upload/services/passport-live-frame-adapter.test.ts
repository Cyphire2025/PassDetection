import { afterEach, expect, it, vi } from "vitest";
import { detectRectangularPassportFrame } from "./passport-rectangular-frame-detector";

afterEach(() => vi.restoreAllMocks());

function camera(readyState: number = HTMLMediaElement.HAVE_CURRENT_DATA) {
  return {
    readyState, videoWidth: 1920, videoHeight: 1080,
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 400, height: 400 }),
  } as HTMLVideoElement;
}

it("maps the displayed object-cover guide and retains its ten-percent live context", () => {
  const video = camera();
  const guide = { getBoundingClientRect: () => ({ left: 50, top: 120, width: 320, height: 200 }) } as HTMLElement;
  const drawImage = vi.fn();
  const canvas = document.createElement("canvas");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage, getImageData: () => ({ data: new Uint8ClampedArray(320 * 200 * 4) }) } as unknown as CanvasRenderingContext2D);
  const result = detectRectangularPassportFrame(video, canvas, guide);
  expect(drawImage).toHaveBeenCalledExactlyOnceWith(video, expect.closeTo(441.6), 216, expect.closeTo(1036.8), 648, 0, 0, 320, 200);
  expect(canvas.width).toBe(320);
  expect(canvas.height).toBe(200);
  expect(result.isDetected).toBe(false);
});

it("uses the full source when its DOM guide cannot be measured", () => {
  const video = camera();
  const guide = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) } as HTMLElement;
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage, getImageData: () => ({ data: new Uint8ClampedArray(320 * 200 * 4) }) } as unknown as CanvasRenderingContext2D);
  detectRectangularPassportFrame(video, document.createElement("canvas"), guide);
  expect(drawImage).toHaveBeenCalledExactlyOnceWith(video, 0, 0, 1920, 1080, 0, 0, 320, 200);
});

it("does not read pixels before the camera has a current frame", () => {
  const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
  expect(detectRectangularPassportFrame(camera(0), document.createElement("canvas"))).toMatchObject({ isDetected: false, status: "checking" });
  expect(context).not.toHaveBeenCalled();
});

it("fails closed if a canvas context cannot be allocated", () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  expect(detectRectangularPassportFrame(camera(), document.createElement("canvas"))).toMatchObject({ isDetected: false, status: "checking", visibleEdges: 0 });
});
