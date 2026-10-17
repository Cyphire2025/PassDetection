import { requestSync } from '../sync-trigger';
import { syncAllTripsWithSummary, syncTripInContext } from '../sync-service';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => true }));
jest.mock('../sync-service', () => ({ syncAllTripsWithSummary: jest.fn(), syncTripInContext: jest.fn(), syncTripFailure: jest.fn() }));

it('makes manual demo refresh local and preserves cancellation', async () => {
  expect(await requestSync({ scope: 'full', reason: 'demo-test' })).toMatchObject({ results: [], failures: [], requestedTripCount: 0 });
  expect(await requestSync({ scope: 'trip', tripId: 'sample', reason: 'demo-test' })).toMatchObject({ results: [], failures: [] });
  expect(syncAllTripsWithSummary).not.toHaveBeenCalled();
  expect(syncTripInContext).not.toHaveBeenCalled();
  const controller = new AbortController();
  controller.abort(new Error('Cancelled demo refresh'));
  await expect(requestSync({ scope: 'full', reason: 'demo-test' }, { signal: controller.signal })).rejects.toThrow('Cancelled demo refresh');
});
