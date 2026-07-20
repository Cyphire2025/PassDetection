export const VISA_READINESS_PROMOTION_WINDOW = 3;
export const VISA_READINESS_PROMOTION_SAMPLES = 2;
export const VISA_READINESS_RELEASE_SAMPLES = 4;

export interface VisaReadinessHysteresis {
  ready: boolean;
  promotionSamples: boolean[];
  failingSamples: number;
}

export const INITIAL_VISA_READINESS: VisaReadinessHysteresis = {
  ready: false,
  promotionSamples: [],
  failingSamples: 0,
};

/**
 * Visa readiness preserves the existing two-of-latest-three promotion rule,
 * then tolerates longer detector/background noise before releasing. This is
 * intentionally Visa-only so passport readiness remains unchanged.
 */
export function updateVisaReadinessHysteresis(
  previous: VisaReadinessHysteresis,
  nextFrameReady: boolean,
): VisaReadinessHysteresis {
  const promotionSamples = [
    ...previous.promotionSamples,
    nextFrameReady,
  ].slice(-VISA_READINESS_PROMOTION_WINDOW);
  const passingSamples = promotionSamples.filter(Boolean).length;
  const promoted = (
    promotionSamples.length === VISA_READINESS_PROMOTION_WINDOW
    && passingSamples >= VISA_READINESS_PROMOTION_SAMPLES
  );
  const failingSamples = previous.ready && !nextFrameReady
    ? Math.min(VISA_READINESS_RELEASE_SAMPLES, previous.failingSamples + 1)
    : 0;
  return {
    ready: previous.ready
      ? failingSamples < VISA_READINESS_RELEASE_SAMPLES
      : promoted,
    promotionSamples,
    failingSamples,
  };
}

/**
 * Serializes every inference for one MediaPipe detector instance. Rejections
 * do not poison the queue, and drain() waits for both active and queued work.
 */
export class SerializedVisaInferenceQueue {
  private tail: Promise<void> = Promise.resolve();
  private pendingOperations = 0;

  run<T>(operation: () => Promise<T>): Promise<T> {
    this.pendingOperations += 1;
    const result = this.tail.then(operation, operation);
    this.tail = result.then(
      () => undefined,
      () => undefined,
    ).finally(() => {
      this.pendingOperations -= 1;
    });
    return result;
  }

  drain(): Promise<void> {
    return this.tail;
  }

  get busy(): boolean {
    return this.pendingOperations > 0;
  }
}

/**
 * Waits for safe detector drainage without holding camera tracks forever.
 * `true` means all inference settled; `false` means the caller must abandon
 * that detector generation and must never enqueue more work on its instance.
 */
export async function waitForVisaInferenceDrain(
  queue: SerializedVisaInferenceQueue,
  timeoutMs: number,
): Promise<boolean> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      queue.drain().then(() => true),
      new Promise<false>((resolve) => {
        timeoutId = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

export const VISA_CAMERA_SAFE_RETRY_MESSAGE =
  "Camera checks had a temporary problem and were restarted. Please align again and retry.";

const MEDIAPIPE_RUNTIME_ERROR_PATTERN =
  /(?:out of bounds memory access|invoker\(|webassembly|wasm|memory access|abort(?:ed)?\()/i;

export function isMediaPipeRuntimeFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return MEDIAPIPE_RUNTIME_ERROR_PATTERN.test(message);
}

/**
 * Detector failures must never expose raw WebAssembly implementation details
 * to a client. Every send failure faults that detector instance; known WASM
 * errors and ordinary detector errors share one stable retry instruction.
 */
export class VisaDetectorInferenceError extends Error {
  readonly resetDetector = true;
  readonly runtimeFailure: boolean;

  constructor(error: unknown) {
    super(VISA_CAMERA_SAFE_RETRY_MESSAGE);
    this.name = "VisaDetectorInferenceError";
    this.runtimeFailure = isMediaPipeRuntimeFailure(error);
  }
}
