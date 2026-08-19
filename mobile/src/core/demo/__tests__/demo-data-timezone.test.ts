import { withAccountTransaction } from '@/core/storage/database';

import { demoPrincipal, seedDemoAccount } from '../demo-data';

jest.mock('@/core/storage/database', () => ({
  withAccountTransaction: jest.fn(async (database, task) => task(database)),
}));

const mockedTransaction = jest.mocked(withAccountTransaction);

describe('demo trip timezone seeding', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('persists a canonical IANA timezone for every seeded trip', async () => {
    const database = {
      runAsync: jest.fn(async (..._arguments: unknown[]) => ({ changes: 1 })),
    };

    await seedDemoAccount(database as never, {
      namespace: 'demo.manager',
      principal: demoPrincipal('client_manager'),
    });

    expect(mockedTransaction).toHaveBeenCalledTimes(1);
    const tripUpserts = database.runAsync.mock.calls.filter(([sql]) => (
      String(sql).includes('INSERT INTO trips')
    ));
    expect(tripUpserts).toHaveLength(2);
    expect(tripUpserts.map(([sql]) => String(sql))).toEqual([
      expect.stringContaining('return_date, timezone'),
      expect.stringContaining('return_date, timezone'),
    ]);
    expect(tripUpserts.map((call) => call[9])).toEqual([
      'Asia/Singapore',
      'Asia/Dubai',
    ]);
  });
});
