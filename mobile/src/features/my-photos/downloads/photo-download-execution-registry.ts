import type { MyPhotosContext } from '../data/my-photos-context';

type ActiveExecution = Readonly<{
  controller: AbortController;
  settled: Promise<void>;
  resolveSettled: () => void;
}>;

/** Owns the cancellation/settlement fence for active native transfers. A
 * caller must await `abortAndWait` before deleting encrypted staging. */
export class PhotoDownloadExecutionRegistry {
  private readonly active = new Map<string, ActiveExecution>();

  begin(context: MyPhotosContext, jobId: string, parent: AbortSignal): AbortSignal {
    const key = this.key(context, jobId);
    if (this.active.has(key)) throw new Error('Photo download is already executing.');
    const controller = new AbortController();
    let resolveSettled!: () => void;
    const settled = new Promise<void>((resolve) => { resolveSettled = resolve; });
    this.active.set(key, { controller, settled, resolveSettled });
    return AbortSignal.any([parent, controller.signal, context.signal]);
  }

  finish(context: MyPhotosContext, jobId: string): void {
    const key = this.key(context, jobId);
    const execution = this.active.get(key);
    if (!execution) return;
    this.active.delete(key);
    execution.resolveSettled();
  }

  async abortAndWait(
    context: MyPhotosContext,
    jobId: string,
    reason: Error,
    timeoutMs = 30_000,
  ): Promise<void> {
    const execution = this.active.get(this.key(context, jobId));
    if (!execution) return;
    execution.controller.abort(reason);
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      await Promise.race([
        execution.settled,
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error('Photo download did not settle after cancellation.')),
            timeoutMs,
          );
        }),
      ]);
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  async abortContextAndWait(
    context: MyPhotosContext,
    reason: Error,
    timeoutMs = 30_000,
  ): Promise<void> {
    await this.abortMatchingAndWait(
      `${context.namespace}|${context.tripId}|${context.passengerId}|`,
      reason,
      timeoutMs,
    );
  }

  async abortNamespaceAndWait(
    namespace: string,
    reason: Error,
    timeoutMs = 30_000,
  ): Promise<void> {
    await this.abortMatchingAndWait(`${namespace}|`, reason, timeoutMs);
  }

  abortContext(context: MyPhotosContext, reason: Error): void {
    const prefix = `${context.namespace}|${context.tripId}|${context.passengerId}|`;
    for (const [key, execution] of this.active) {
      if (key.startsWith(prefix)) execution.controller.abort(reason);
    }
  }

  private async abortMatchingAndWait(
    prefix: string,
    reason: Error,
    timeoutMs: number,
  ): Promise<void> {
    const executions = [...this.active]
      .filter(([key]) => key.startsWith(prefix))
      .map(([, execution]) => execution);
    if (!executions.length) return;
    for (const execution of executions) execution.controller.abort(reason);
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      await Promise.race([
        Promise.all(executions.map((execution) => execution.settled)).then(() => undefined),
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error('Photo downloads did not settle before the account locked.')),
            timeoutMs,
          );
        }),
      ]);
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  private key(context: MyPhotosContext, jobId: string): string {
    return `${context.namespace}|${context.tripId}|${context.passengerId}|${jobId}`;
  }
}
