import type { MyPhotosContext } from '../my-photos-context';
import { purgeMyPhotosPrivateTripData } from '../my-photos-repository';

const mockRunAsync = jest.fn();
const mockDatabase = { runAsync: mockRunAsync };

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(async () => mockDatabase),
  withAccountTransaction: jest.fn(async (_database, operation) => operation(mockDatabase)),
}));

jest.mock('../../api/my-photos-api', () => ({
  getMyPhotosPage: jest.fn(),
  getMyPhotosSummary: jest.fn(),
}));

const context = {
  namespace: 'tenant.account',
  sessionId: 'session',
  agencyId: 'tenant',
  principalId: 'account',
  role: 'passenger',
  tripId: '11111111-1111-4111-8111-111111111111',
  passengerId: '22222222-2222-4222-8222-222222222222',
  signal: new AbortController().signal,
} satisfies MyPhotosContext;

beforeEach(() => {
  jest.clearAllMocks();
  mockRunAsync.mockResolvedValue({ changes: 1 });
});

test('purges only the disabled owner while retaining the capability summary', async () => {
  const assertActive = jest.fn();

  await purgeMyPhotosPrivateTripData(context, assertActive);

  expect(assertActive).toHaveBeenCalled();
  expect(mockRunAsync).toHaveBeenCalledTimes(5);
  const sql = mockRunAsync.mock.calls.map(([statement]) => String(statement)).join('\n');
  expect(sql).toContain('DELETE FROM my_photos_downloads');
  expect(sql).toContain('DELETE FROM my_photos_download_batches');
  expect(sql).toContain('DELETE FROM my_photos_reconciliation_state');
  expect(sql).toContain('DELETE FROM my_photos_page_cache');
  expect(sql).toContain('DELETE FROM my_photos_cursor_cache');
  expect(sql).not.toContain('my_photos_summary_cache');
  for (const call of mockRunAsync.mock.calls) {
    expect(call.slice(1)).toEqual([
      context.namespace,
      context.tripId,
      context.passengerId,
    ]);
  }
});
