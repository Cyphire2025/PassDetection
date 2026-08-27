export const MY_PHOTOS_RECONCILIATION_PAGE_SIZE = 25;
export const MY_PHOTOS_RECONCILIATION_MAX_ROWS_PER_ACTIVATION = 50;
export const MY_PHOTOS_RECONCILIATION_MAX_FULL_INSPECTIONS_PER_ACTIVATION = 1;

/** Explicit activation budget keeps startup work independent of manifest size.
 * The durable keyset cursor resumes the next slice on a later activation. */
export class PhotoDownloadReconciliationBudget {
  private rows = 0;
  private fullInspections = 0;

  canReadPage(): boolean {
    return this.rows < MY_PHOTOS_RECONCILIATION_MAX_ROWS_PER_ACTIVATION;
  }

  recordRows(count: number): void {
    if (!Number.isSafeInteger(count) || count < 0) {
      throw new Error('Photo reconciliation row count is invalid.');
    }
    this.rows = Math.min(
      MY_PHOTOS_RECONCILIATION_MAX_ROWS_PER_ACTIVATION,
      this.rows + count,
    );
  }

  claimFullInspection(): boolean {
    if (
      this.fullInspections
      >= MY_PHOTOS_RECONCILIATION_MAX_FULL_INSPECTIONS_PER_ACTIVATION
    ) return false;
    this.fullInspections += 1;
    return true;
  }

  snapshot(): Readonly<{ rows: number; fullInspections: number }> {
    return { rows: this.rows, fullInspections: this.fullInspections };
  }
}
