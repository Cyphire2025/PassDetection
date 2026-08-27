import type * as SQLite from 'expo-sqlite';

import { MY_PHOTOS_STORAGE_SCHEMA_SQL } from '@/features/my-photos/data/my-photos-storage-schema';

import { CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL } from './database-attendance-recovery-schema';

type TableColumnRow = Readonly<{ name: string }>;

/** Additively reconciles the two independently developed v25 feature slices.
 * Column discovery makes this safe for either historical v25 shape. */
export async function reconcileVersion26Schemas(
  transaction: SQLite.SQLiteDatabase,
): Promise<void> {
  const columns = await transaction.getAllAsync<TableColumnRow>('PRAGMA table_info(attendance_sessions)');
  const names = new Set(columns.map((column) => column.name));
  const alterations: string[] = [];
  if (!names.has('scheduled_starts_at')) {
    alterations.push('ALTER TABLE attendance_sessions ADD COLUMN scheduled_starts_at TEXT;');
  }
  if (!names.has('scheduled_ends_at')) {
    alterations.push('ALTER TABLE attendance_sessions ADD COLUMN scheduled_ends_at TEXT;');
  }
  if (!names.has('schedule_timezone')) {
    alterations.push('ALTER TABLE attendance_sessions ADD COLUMN schedule_timezone TEXT;');
  }
  if (!names.has('schedule_version')) {
    alterations.push(`ALTER TABLE attendance_sessions ADD COLUMN schedule_version INTEGER NOT NULL DEFAULT 1
      CHECK (schedule_version >= 1);`);
  }
  if (alterations.length > 0) await transaction.execAsync(alterations.join('\n'));
  await transaction.execAsync(`
    CREATE INDEX IF NOT EXISTS idx_attendance_sessions_schedule
      ON attendance_sessions(
        account_namespace, trip_id, scheduled_starts_at, scheduled_ends_at
      );
    ${CURRENT_ATTENDANCE_RECOVERY_SCHEMA_SQL}
    ${MY_PHOTOS_STORAGE_SCHEMA_SQL}
    PRAGMA user_version = 26;
  `);
}
