import { DatabaseSync } from 'node:sqlite';
import { principalAccountNamespace } from '@/core/auth/types';
import { migrateAccountDatabase } from '@/core/storage/database-schema';
import { AttendanceSessionSchema } from '@/features/coordinator/api/coordinator-contracts';
import { ManagerRosterSchema } from '@/features/manager/api/manager-contracts';
import { isItineraryDocument } from '@/features/content/data/passenger-document-policy';
import { demoPrincipal, seedDemoAccount } from '../demo-data';
import { demoOperationsRequest, demoPassengerDetail, demoRoster, markDemoAttendance } from '../demo-operations';
type SQLInputValue = string | number | bigint | null | Uint8Array;

let mockPrincipal = demoPrincipal('coordinator');
jest.mock('expo-crypto', () => ({ randomUUID: () => '00000000-0000-4000-8000-000000000999' }));
let mockDatabase: ReturnType<typeof adapter>;
jest.mock('@/core/demo/demo-mode', () => ({ assertDemoMode: jest.fn() }));
jest.mock('@/core/auth/session-store', () => ({ useSessionStore: { getState: () => ({ session: { principal: mockPrincipal } }) } }));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: async () => mockDatabase,
  withAccountTransaction: async (database: unknown, task: (db: unknown) => Promise<void>) => task(database),
}));

function adapter(sqlite: DatabaseSync) {
  return {
    execAsync: async (sql: string) => sqlite.exec(sql),
    runAsync: async (sql: string, ...parameters: SQLInputValue[]) => sqlite.prepare(sql).run(...parameters),
    getFirstAsync: async (sql: string, ...parameters: SQLInputValue[]) => sqlite.prepare(sql).get(...parameters) ?? null,
    getAllAsync: async (sql: string, ...parameters: SQLInputValue[]) => sqlite.prepare(sql).all(...parameters),
  };
}

describe('standalone operations with the real SQLite schema', () => {
  let sqlite: DatabaseSync;
  beforeEach(async () => {
    sqlite = new DatabaseSync(':memory:');
    mockDatabase = adapter(sqlite);
    mockPrincipal = demoPrincipal('coordinator');
    await migrateAccountDatabase(mockDatabase as never, async (task) => task(mockDatabase as never));
  });
  afterEach(() => sqlite.close());
  async function seed() {
    await seedDemoAccount(mockDatabase as never, { namespace: principalAccountNamespace(mockPrincipal), principal: mockPrincipal });
  }
  it('gives the passenger home screen an offline itinerary PDF', async () => {
    mockPrincipal = demoPrincipal('passenger');
    await seed();
    const documents = await mockDatabase.getAllAsync(
      'SELECT category, scope, offline_available, size_bytes FROM document_metadata',
    ) as { category: string; scope: string; offline_available: number; size_bytes: number }[];
    const itinerary = documents.find((document) => isItineraryDocument(document.category));
    expect(itinerary).toMatchObject({ scope: 'common', offline_available: 1 });
    expect(itinerary?.size_bytes).toBeGreaterThan(0);
  });
  it('seeds readable sample records and records attendance once per passenger', async () => {
    await seed();
    const trip = '00000000-0000-4000-8000-000000000301';
    const roster = await demoRoster(trip);
    expect(roster).toHaveLength(14);
    const missing = roster.find((item) => item.attendance_status === 'missing')!;
    expect((await demoPassengerDetail(trip, missing.id)).display_name).toBe(missing.display_name);
    expect(await markDemoAttendance(trip, missing.id)).toContain('marked present');
    expect(await markDemoAttendance(trip, missing.id)).toContain('already counted');
    const sessions = await demoOperationsRequest(`/mobile/coordinator/groups/${trip}/attendance/sessions`) as { items: unknown[] };
    expect(AttendanceSessionSchema.parse(sessions.items[0]).scanned_count).toBe(11);
    expect((await demoRoster(trip)).find((item) => item.id === missing.id)?.attendance_status).toBe('present');
    await expect(demoPassengerDetail(trip, '00000000-0000-4000-8000-000000999999')).rejects.toThrow('not found');
    await expect(demoRoster('00000000-0000-4000-8000-000000000201')).rejects.toThrow('not assigned');
  });
  it('lets a manager inspect, create and close local activities with validated schemas', async () => {
    mockPrincipal = demoPrincipal('client_manager');
    await seed();
    const path = '/mobile/manager/groups/00000000-0000-4000-8000-000000000201';
    const roster = ManagerRosterSchema.parse(await demoOperationsRequest(`${path}/passengers`));
    expect(roster.total).toBe(14);
    const created = AttendanceSessionSchema.parse(await demoOperationsRequest(`${path}/attendance/sessions`, 'POST', { name: 'Demo coach boarding' }));
    expect(created.assigned_count).toBe(14);
    expect(created.scanned_count).toBe(0);
    const completed = AttendanceSessionSchema.parse(await demoOperationsRequest(`${path}/attendance/sessions/${created.id}/complete`, 'PUT', {}));
    expect(completed.status).toBe('completed');
    await expect(markDemoAttendance('00000000-0000-4000-8000-000000000201', roster.items[0]!.id)).rejects.toThrow('Coordinator demo');
    await expect(demoOperationsRequest(path.replace('/manager/', '/coordinator/') + '/passengers')).rejects.toThrow('different sample role');
  });
});
