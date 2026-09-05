import type { Detection, FaceDetection } from "@mediapipe/face_detection";
import { visaFaceDetectionAssetUrl } from "@/config/visa-face-detection-assets";
import { initializeVisaFaceDetection, loadVisaFaceDetection } from "./visa-face-detection-loader";

type Detector = Pick<FaceDetection, "initialize" | "send" | "onResults" | "close">;
type Session = {
  detector: Detector | null;
  ready: Promise<Detector>;
  operations: Set<Promise<unknown>>;
};

const DETECTOR_TIMEOUT_MS = 8_000;
const DETECTOR_IDLE_MS = 60_000;
const DETECTOR_RETRY_MESSAGE =
  "Automatic face detection could not finish. Please try again or choose another studio photo.";
class VisaPhotoDetectorTimeoutError extends Error {
  constructor() {
    super("Automatic face detection stopped responding. Please reload this page and choose your photo again.");
    this.name = "VisaPhotoDetectorTimeoutError";
  }
}

/**
 * One upload-only instance, with serialized inference and bounded idle storage.
 * Failed generations are drained before closing or starting a replacement; a
 * late WASM callback can never satisfy a newer photo's validation. Live camera
 * detection retains its existing lifecycle and quality policy.
 */
export class VisaPhotoFaceDetector {
  private session: Session | null = null;
  private tail: Promise<void> = Promise.resolve();
  private retirement: Promise<void> = Promise.resolve();
  private warming: Promise<void> | null = null;
  private pending = 0;
  private idleTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly loadDetector: () => Promise<Detector>,
    private readonly timeoutMs = DETECTOR_TIMEOUT_MS,
    private readonly idleMs = DETECTOR_IDLE_MS,
  ) {}

  prewarm(): Promise<void> {
    if (!this.warming) {
      this.warming = this.run(async () => {
        // The first send also loads the graph and compiles GPU shaders. Do it
        // while the user is choosing a file, without using any personal image.
        const blank = document.createElement("canvas");
        blank.width = 96;
        blank.height = 144;
        const context = blank.getContext("2d");
        if (!context) throw new Error(DETECTOR_RETRY_MESSAGE);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, blank.width, blank.height);
        await this.infer(blank);
      }).catch((error: unknown) => {
        this.warming = null;
        throw error;
      });
    }
    return this.warming;
  }

  detect(image: HTMLImageElement): Promise<Detection[]> {
    return this.run(() => this.infer(image));
  }

  private run<T>(operation: () => Promise<T>): Promise<T> {
    clearTimeout(this.idleTimer);
    this.pending += 1;
    const result = this.tail.then(operation);
    this.tail = result.then(() => undefined, () => undefined);
    return result.finally(() => {
      this.pending -= 1;
      if (this.pending === 0) {
        this.idleTimer = setTimeout(() => this.retire(), this.idleMs);
      }
    });
  }

  private async getSession(): Promise<Session> {
    // A timed-out send may still be executing. Never overlap a replacement
    // with it, and never make the user wait indefinitely for that drainage.
    await withDeadline(this.retirement, this.timeoutMs);
    if (!this.session) {
      const session: Session = {
        detector: null,
        operations: new Set(),
        ready: this.loadDetector().then(async (detector) => {
          session.detector = detector;
          await initializeVisaFaceDetection(detector);
          return detector;
        }),
      };
      this.session = session;
    }
    return this.session;
  }

  private async infer(image: HTMLImageElement | HTMLCanvasElement): Promise<Detection[]> {
    try {
      const session = await this.getSession();
      const detector = await withDeadline(session.ready, this.timeoutMs);
      let resolveResults!: (detections: Detection[]) => void;
      const results = new Promise<Detection[]>((resolve) => { resolveResults = resolve; });
      detector.onResults((value) => resolveResults(value.detections));
      const send = detector.send({ image });
      session.operations.add(send);
      // Retain the actual send, not its timeout wrapper, for safe disposal.
      void send.then(
        () => session.operations.delete(send),
        () => session.operations.delete(send),
      );
      const [detections] = await withDeadline(Promise.all([results, send]), this.timeoutMs);
      return detections;
    } catch (error) {
      this.retire();
      console.error("Uploaded Visa Photo face detection failed", error);
      throw new Error(error instanceof VisaPhotoDetectorTimeoutError ? error.message : DETECTOR_RETRY_MESSAGE);
    }
  }

  private retire(): void {
    clearTimeout(this.idleTimer);
    const session = this.session;
    this.session = null;
    this.warming = null;
    if (!session) return;
    const previousRetirement = this.retirement;
    this.retirement = Promise.allSettled([
      previousRetirement,
      session.ready,
      ...session.operations,
    ]).then(async () => {
      // Do not abandon close() on a timer: the next generation also waits for
      // it, and its own deadline provides a bounded, recoverable user error.
      await session.detector?.close();
    }).catch((error: unknown) => {
      console.error("Uploaded Visa Photo detector cleanup failed", error);
    });
  }
}

function withDeadline<T>(operation: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new VisaPhotoDetectorTimeoutError()), timeoutMs);
    operation.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

const uploadDetector = new VisaPhotoFaceDetector(async () => {
  const { FaceDetection } = await loadVisaFaceDetection();
  const detector = new FaceDetection({ locateFile: visaFaceDetectionAssetUrl });
  detector.setOptions({ model: "short", selfieMode: false, minDetectionConfidence: 0.65 });
  return detector;
});

export function detectVisaPhotoFaces(image: HTMLImageElement): Promise<Detection[]> {
  return uploadDetector.detect(image);
}

export function prewarmUploadedVisaPhotoDetector(): Promise<void> {
  return uploadDetector.prewarm();
}
