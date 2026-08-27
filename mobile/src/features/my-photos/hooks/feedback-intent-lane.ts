/** Serializes feedback writes per asset while allowing different assets to
 * proceed independently. Each accepted local intent receives a monotonic
 * revision that callers can include in their idempotency identity. */
export class FeedbackIntentLane {
  private readonly lanes = new Map<string, Promise<void>>();
  private readonly revisions = new Map<string, number>();

  reset(): void {
    this.lanes.clear();
    this.revisions.clear();
  }

  async run<T>(assetId: string, operation: (revision: number) => Promise<T>): Promise<T> {
    const revision = (this.revisions.get(assetId) ?? 0) + 1;
    this.revisions.set(assetId, revision);
    const previous = this.lanes.get(assetId) ?? Promise.resolve();
    let release!: () => void;
    const lane = new Promise<void>((resolve) => { release = resolve; });
    this.lanes.set(assetId, lane);
    await previous.catch(() => undefined);
    try {
      return await operation(revision);
    } finally {
      release();
      if (this.lanes.get(assetId) === lane) this.lanes.delete(assetId);
    }
  }
}
