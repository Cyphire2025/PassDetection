import type { Detection, Results } from "@mediapipe/face_detection";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VisaPhotoFaceDetector } from "./visa-photo-upload-detector";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fakeDetector() {
  let callback: (results: Results) => void = () => undefined;
  const detector = {
    initialize: vi.fn(async (): Promise<void> => undefined),
    close: vi.fn(async (): Promise<void> => undefined),
    onResults: vi.fn((next: typeof callback) => { callback = next; }),
    send: vi.fn(async () => { detector.emit([]); }),
    emit: (detections: Detection[]) => callback({ detections } as Results),
  };
  return detector;
}

describe("uploaded visa photo detector lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      fillStyle: "", fillRect: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shares warmup and reuses initialized WASM across photo changes", async () => {
    const driver = fakeDetector();
    const load = vi.fn(async () => driver);
    const detector = new VisaPhotoFaceDetector(load, 100, 1_000);
    const warm = detector.prewarm();
    expect(detector.prewarm()).toBe(warm);
    await warm;
    await detector.detect(new Image());
    await detector.detect(new Image());
    expect(load).toHaveBeenCalledTimes(1);
    expect(driver.initialize).toHaveBeenCalledTimes(1);
    expect(driver.send).toHaveBeenCalledTimes(3);
    expect(driver.close).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(driver.close).toHaveBeenCalledOnce();
    await detector.detect(new Image());
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("serializes images and pairs each result with its own completed send", async () => {
    const driver = fakeDetector();
    const send = deferred<void>();
    const face = { boundingBox: { xCenter: 0.5 } } as Detection;
    driver.send.mockImplementationOnce(() => send.promise);
    const detector = new VisaPhotoFaceDetector(async () => driver, 100, 1_000);
    const first = detector.detect(new Image());
    const second = detector.detect(new Image());
    await vi.advanceTimersByTimeAsync(0);
    expect(driver.send).toHaveBeenCalledTimes(1);
    driver.emit([face]);
    await vi.advanceTimersByTimeAsync(0);
    expect(driver.send).toHaveBeenCalledTimes(1);
    send.resolve();
    expect(await first).toEqual([face]);
    expect(await second).toEqual([]);
    expect(driver.send).toHaveBeenCalledTimes(2);
  });

  it("never closes a timed-out active inference and blocks replacement until it settles", async () => {
    const old = fakeDetector();
    const next = fakeDetector();
    const active = deferred<void>();
    old.send.mockImplementationOnce(() => active.promise);
    const load = vi.fn().mockResolvedValueOnce(old).mockResolvedValue(next);
    const detector = new VisaPhotoFaceDetector(load, 100, 1_000);
    const first = detector.detect(new Image()).catch((error: Error) => error);
    await vi.advanceTimersByTimeAsync(101);
    expect(await first).toBeInstanceOf(Error);
    expect(old.close).not.toHaveBeenCalled();
    const retry = detector.detect(new Image());
    await vi.advanceTimersByTimeAsync(0);
    expect(load).toHaveBeenCalledTimes(1);
    // A late callback belongs only to the abandoned request.
    old.emit([{ boundingBox: {} } as Detection]);
    active.resolve();
    expect(await retry).toEqual([]);
    expect(old.close).toHaveBeenCalledOnce();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("returns a bounded retry error while abandoned WASM remains stuck", async () => {
    const driver = fakeDetector();
    driver.send.mockImplementationOnce(() => new Promise(() => undefined));
    const load = vi.fn(async () => driver);
    const detector = new VisaPhotoFaceDetector(load, 100, 1_000);
    const first = detector.detect(new Image()).catch((error: Error) => error);
    await vi.advanceTimersByTimeAsync(101);
    await first;
    const retry = detector.detect(new Image()).catch((error: Error) => error);
    await vi.advanceTimersByTimeAsync(101);
    expect((await retry as Error).message).toMatch(/reload this page/);
    expect(load).toHaveBeenCalledTimes(1);
    expect(driver.close).not.toHaveBeenCalled();
  });

  it("recovers from failed warmup without treating it as photo acceptance", async () => {
    const bad = fakeDetector();
    bad.initialize.mockRejectedValueOnce(new Error("asset unavailable"));
    const good = fakeDetector();
    const load = vi.fn().mockResolvedValueOnce(bad).mockResolvedValue(good);
    const detector = new VisaPhotoFaceDetector(load, 100, 1_000);
    await expect(detector.prewarm()).rejects.toThrow(/^Automatic face detection/);
    expect(bad.send).not.toHaveBeenCalled();
    expect(await detector.detect(new Image())).toEqual([]);
    expect(bad.close).toHaveBeenCalledOnce();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("waits to close initialization that finishes after the timeout", async () => {
    const driver = fakeDetector();
    const initialization = deferred<void>();
    driver.initialize.mockImplementationOnce(() => initialization.promise);
    const detector = new VisaPhotoFaceDetector(async () => driver, 100, 1_000);
    const result = detector.detect(new Image()).catch((error: Error) => error);
    await vi.advanceTimersByTimeAsync(101);
    expect(await result).toBeInstanceOf(Error);
    expect(driver.close).not.toHaveBeenCalled();
    initialization.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(driver.close).toHaveBeenCalledOnce();
    expect(driver.send).not.toHaveBeenCalled();
  });
});
