import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("same-origin MediaPipe API loading", () => {
  beforeEach(() => { vi.resetModules(); });
  afterEach(() => {
    document.head.querySelectorAll("script[src*='/mediapipe/']").forEach((script) => script.remove());
    Reflect.deleteProperty(window, "FaceDetection");
  });

  it("serializes startup across upload and camera instances, including a failed generation", async () => {
    const { initializeVisaFaceDetection } = await import("./visa-face-detection-loader");
    let fail!: (error: Error) => void;
    const camera = { initialize: vi.fn(() => new Promise<void>((_, reject) => { fail = reject; })) };
    const upload = { initialize: vi.fn(async (): Promise<void> => undefined) };
    const first = initializeVisaFaceDetection(camera);
    const rejected = expect(first).rejects.toThrow("asset unavailable");
    const second = initializeVisaFaceDetection(upload);
    await Promise.resolve();
    expect(camera.initialize).toHaveBeenCalledOnce();
    expect(upload.initialize).not.toHaveBeenCalled();
    fail(new Error("asset unavailable"));
    await rejected;
    await second;
    expect(upload.initialize).toHaveBeenCalledOnce();
  });

  it("shares one versioned request and retains the loaded constructor", async () => {
    const { loadVisaFaceDetection } = await import("./visa-face-detection-loader");
    const first = loadVisaFaceDetection();
    expect(loadVisaFaceDetection()).toBe(first);
    const scripts = document.head.querySelectorAll<HTMLScriptElement>("script[src*='/mediapipe/']");
    expect(scripts).toHaveLength(1);
    expect(scripts[0].src).toContain("/mediapipe/face_detection/face_detection.js?v=");
    class FaceDetection {}
    Object.defineProperty(window, "FaceDetection", { value: FaceDetection, configurable: true });
    scripts[0].dispatchEvent(new Event("load"));
    expect(await first).toEqual({ FaceDetection });
    expect(loadVisaFaceDetection()).toBe(first);
  });

  it("rejects a failed script request and allows a fresh download", async () => {
    const { loadVisaFaceDetection } = await import("./visa-face-detection-loader");
    const first = loadVisaFaceDetection();
    const rejected = expect(first).rejects.toThrow("could not be downloaded");
    const failedScript = document.head.querySelector("script[src*='/mediapipe/']")!;
    failedScript.dispatchEvent(new Event("error"));
    await rejected;
    expect(failedScript.isConnected).toBe(false);
    const retry = loadVisaFaceDetection();
    expect(retry).not.toBe(first);
    class FaceDetection {}
    Object.defineProperty(window, "FaceDetection", { value: FaceDetection, configurable: true });
    document.head.querySelector("script[src*='/mediapipe/']")!.dispatchEvent(new Event("load"));
    expect(await retry).toEqual({ FaceDetection });
  });

  it("does not treat an incomplete script as a working detector", async () => {
    const { loadVisaFaceDetection } = await import("./visa-face-detection-loader");
    const first = loadVisaFaceDetection();
    const rejected = expect(first).rejects.toThrow("could not be loaded");
    document.head.querySelector("script[src*='/mediapipe/']")!.dispatchEvent(new Event("load"));
    await rejected;
    expect(document.head.querySelector("script[src*='/mediapipe/']")).toBeNull();
  });
});
