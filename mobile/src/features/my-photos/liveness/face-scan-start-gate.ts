export type FaceScanStartDisposition = 'clear_idempotency_key' | 'retain_idempotency_key';

export function faceScanStartDisposition(input: Readonly<{
  sessionCreated: boolean;
  operationAborted: boolean;
  transportAmbiguous: boolean;
}>): FaceScanStartDisposition {
  return !input.sessionCreated && (input.operationAborted || input.transportAmbiguous)
    ? 'retain_idempotency_key'
    : 'clear_idempotency_key';
}

/** Coalesces rapid scan-entry taps synchronously. A transport-ambiguous start
 * retains the same mutation identity for the next explicit retry, while a
 * definitive server response consumes it. */
export class FaceScanStartGate {
  private inFlight: Promise<void> | null = null;
  private requestId: string | null = null;

  constructor(private readonly createRequestId: () => string) {}

  run(
    operation: (requestId: string) => Promise<FaceScanStartDisposition>,
  ): Promise<void> {
    if (this.inFlight) return this.inFlight;
    const requestId = this.requestId ?? this.createRequestId();
    this.requestId = requestId;
    let task!: Promise<void>;
    task = operation(requestId)
      .then((disposition) => {
        if (disposition === 'clear_idempotency_key' && this.requestId === requestId) {
          this.requestId = null;
        }
      })
      .finally(() => {
        if (this.inFlight === task) this.inFlight = null;
      });
    this.inFlight = task;
    return task;
  }

  reset(): void {
    this.requestId = null;
  }
}
