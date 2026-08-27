import {
  MY_PHOTOS_RECONCILIATION_MAX_ROWS_PER_ACTIVATION,
  MY_PHOTOS_RECONCILIATION_PAGE_SIZE,
  PhotoDownloadReconciliationBudget,
} from '../photo-download-reconciliation-policy';

describe('My Photos incremental reconciliation budget', () => {
  it('bounds work per activation for a 5,000-row durable manifest', () => {
    const budget = new PhotoDownloadReconciliationBudget();
    let inspectedRows = 0;
    let fullInspections = 0;
    while (inspectedRows < 5_000 && budget.canReadPage()) {
      const pageSize = Math.min(MY_PHOTOS_RECONCILIATION_PAGE_SIZE, 5_000 - inspectedRows);
      budget.recordRows(pageSize);
      inspectedRows += pageSize;
      if (budget.claimFullInspection()) fullInspections += 1;
    }

    expect(inspectedRows).toBe(MY_PHOTOS_RECONCILIATION_MAX_ROWS_PER_ACTIVATION);
    expect(inspectedRows).toBeLessThan(5_000);
    expect(fullInspections).toBe(1);
    expect(budget.snapshot()).toEqual({ rows: 50, fullInspections: 1 });
  });
});
