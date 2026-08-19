import * as Crypto from 'expo-crypto';
import type * as SQLite from 'expo-sqlite';

export const LOCAL_ROSTER_PAGE_SIZE = 100;
export const LOCAL_ROSTER_CURSOR_TTL_MS = 24 * 60 * 60 * 1_000;

const LOCAL_ROSTER_CURSOR_PREFIX = 'local:v1:';
const LOCAL_ROSTER_SEARCH_MAX_CODE_POINTS = 120;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type LocalRosterFilter = 'all' | 'rooming' | 'meals';

export type LocalRosterItem = Readonly<{
  id: string;
  display_name: string;
  employee_code: string | null;
  attendance_status: 'not_marked' | 'present' | 'missing' | 'excused';
  room_number: string | null;
  meal_preference: string | null;
  has_alert: boolean;
}>;

export type LocalRosterProjectionCompleteness = Readonly<{
  appliedRosterVersion: number | null;
  advertisedRosterVersion: number | null;
  fullReplacementCompleted: boolean;
  isComplete: boolean;
}>;

export type LocalRosterPage = Readonly<{
  items: readonly LocalRosterItem[];
  next_cursor: string | null;
  total: number;
  offline: true;
  projectionCompleteness: LocalRosterProjectionCompleteness;
}>;

type RosterRow = Omit<LocalRosterItem, 'has_alert'> & { has_alert: number };

type CursorBoundary = Readonly<{
  last_display_name: string;
  last_passenger_id: string;
}>;

type NormalizedRosterSearch = Readonly<{
  ftsQuery: string | null;
  matchesNothing: boolean;
  searchKey: string;
}>;

function invalidCursor(): Error {
  return new Error('The offline roster cursor was invalid for this query.');
}

function assertFilter(filter: string): asserts filter is LocalRosterFilter {
  if (filter !== 'all' && filter !== 'rooming' && filter !== 'meals') {
    throw new Error('The offline roster filter was invalid.');
  }
}

/**
 * FTS syntax never receives raw user text. Unicode letters, combining marks,
 * and numbers are extracted into individually quoted prefix terms; operators,
 * quotes, punctuation, and wildcard characters cannot alter the MATCH grammar.
 */
export function normalizeRosterSearch(search: string): NormalizedRosterSearch {
  if (typeof search !== 'string') throw new Error('The offline roster search was invalid.');
  const normalized = search.normalize('NFKC').trim().replace(/\s+/gu, ' ');
  if (Array.from(normalized).length > LOCAL_ROSTER_SEARCH_MAX_CODE_POINTS) {
    throw new Error('The offline roster search was too long.');
  }
  if (!normalized) return { ftsQuery: null, matchesNothing: false, searchKey: '' };

  const rawTokens = normalized
    .toLocaleLowerCase('en-US')
    .match(/[\p{L}\p{N}][\p{L}\p{N}\p{M}]*/gu) ?? [];
  const tokens = [...new Set(rawTokens)];
  if (tokens.length === 0) {
    return { ftsQuery: null, matchesNothing: true, searchKey: '\u0000' };
  }
  return {
    ftsQuery: tokens.map((token) => `"${token.replaceAll('"', '""')}"*`).join(' AND '),
    matchesNothing: false,
    searchKey: tokens.join('\u001f'),
  };
}

function filterPredicate(filter: LocalRosterFilter, tableAlias: string): string {
  if (filter === 'rooming') {
    return ` AND ${tableAlias}.room_number IS NOT NULL
      AND length(trim(${tableAlias}.room_number)) > 0`;
  }
  if (filter === 'meals') {
    return ` AND ${tableAlias}.meal_preference IS NOT NULL
      AND length(trim(${tableAlias}.meal_preference)) > 0`;
  }
  return '';
}

function keysetPredicate(tableAlias: string, boundary: CursorBoundary | null): string {
  if (!boundary) return '';
  return ` AND (
    ${tableAlias}.display_name COLLATE NOCASE > ?
    OR (
      ${tableAlias}.display_name COLLATE NOCASE = ?
      AND ${tableAlias}.id > ?
    )
  )`;
}

function keysetParameters(boundary: CursorBoundary | null): string[] {
  return boundary
    ? [boundary.last_display_name, boundary.last_display_name, boundary.last_passenger_id]
    : [];
}

function parseCursorToken(cursor: string): string {
  if (!cursor.startsWith(LOCAL_ROSTER_CURSOR_PREFIX)) throw invalidCursor();
  const token = cursor.slice(LOCAL_ROSTER_CURSOR_PREFIX.length);
  if (!UUID_PATTERN.test(token)) throw invalidCursor();
  return token.toLowerCase();
}

export function isLocalRosterCursor(cursor: string | null): boolean {
  return cursor !== null && cursor.startsWith(LOCAL_ROSTER_CURSOR_PREFIX);
}

async function projectionCompleteness(
  database: SQLite.SQLiteDatabase,
  accountNamespace: string,
  tripId: string,
): Promise<LocalRosterProjectionCompleteness> {
  const state = await database.getFirstAsync<{
    advertised_roster_version: number;
    roster_projection_complete: number;
    roster_version: number;
  }>(
    `SELECT roster_version, advertised_roster_version, roster_projection_complete
       FROM trips
      WHERE account_namespace = ? AND id = ?
      LIMIT 1`,
    accountNamespace,
    tripId,
  );
  const fullReplacementCompleted = state?.roster_projection_complete === 1;
  const appliedRosterVersion = state?.roster_version ?? null;
  const advertisedRosterVersion = state?.advertised_roster_version ?? null;
  return {
    appliedRosterVersion,
    advertisedRosterVersion,
    fullReplacementCompleted,
    isComplete: Boolean(
      fullReplacementCompleted
      && appliedRosterVersion !== null
      && appliedRosterVersion >= 0
      && appliedRosterVersion === advertisedRosterVersion,
    ),
  };
}

async function resolveCursorBoundary(options: Readonly<{
  accountNamespace: string;
  cursor: string | null;
  database: SQLite.SQLiteDatabase;
  filter: LocalRosterFilter;
  nowMs: number;
  searchKey: string;
  tripId: string;
}>): Promise<CursorBoundary | null> {
  if (!options.cursor) return null;
  const token = parseCursorToken(options.cursor);
  const boundary = await options.database.getFirstAsync<CursorBoundary>(
    `SELECT last_display_name, last_passenger_id
       FROM local_roster_cursors
      WHERE token = ? AND account_namespace = ? AND trip_id = ?
        AND search_key = ? AND filter_key = ? AND expires_at_epoch_ms >= ?
      LIMIT 1`,
    token,
    options.accountNamespace,
    options.tripId,
    options.searchKey,
    options.filter,
    options.nowMs,
  );
  if (!boundary) throw invalidCursor();
  return boundary;
}

async function createCursor(options: Readonly<{
  accountNamespace: string;
  boundary: CursorBoundary;
  createToken: () => string;
  database: SQLite.SQLiteDatabase;
  filter: LocalRosterFilter;
  nowMs: number;
  searchKey: string;
  tripId: string;
}>): Promise<string> {
  const token = options.createToken().toLowerCase();
  if (!UUID_PATTERN.test(token)) throw new Error('The offline roster cursor token was invalid.');
  await options.database.runAsync(
    `INSERT INTO local_roster_cursors
      (token, account_namespace, trip_id, search_key, filter_key,
       last_display_name, last_passenger_id, expires_at_epoch_ms)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    token,
    options.accountNamespace,
    options.tripId,
    options.searchKey,
    options.filter,
    options.boundary.last_display_name,
    options.boundary.last_passenger_id,
    options.nowMs + LOCAL_ROSTER_CURSOR_TTL_MS,
  );
  return `${LOCAL_ROSTER_CURSOR_PREFIX}${token}`;
}

export async function queryLocalRoster(options: Readonly<{
  accountNamespace: string;
  assertActive?: () => void;
  createCursorToken?: () => string;
  cursor?: string | null;
  database: SQLite.SQLiteDatabase;
  filter?: LocalRosterFilter;
  nowMs?: number;
  search?: string;
  tripId: string;
}>): Promise<LocalRosterPage> {
  const filter = options.filter ?? 'all';
  assertFilter(filter);
  const search = normalizeRosterSearch(options.search ?? '');
  const nowMs = options.nowMs ?? Date.now();
  if (!Number.isSafeInteger(nowMs) || nowMs < 0) throw new Error('The offline roster clock was invalid.');
  options.assertActive?.();

  await options.database.runAsync(
    `DELETE FROM local_roster_cursors
      WHERE account_namespace = ? AND expires_at_epoch_ms < ?`,
    options.accountNamespace,
    nowMs,
  );
  options.assertActive?.();
  const boundary = await resolveCursorBoundary({
    accountNamespace: options.accountNamespace,
    cursor: options.cursor ?? null,
    database: options.database,
    filter,
    nowMs,
    searchKey: search.searchKey,
    tripId: options.tripId,
  });
  options.assertActive?.();

  const completeness = await projectionCompleteness(
    options.database,
    options.accountNamespace,
    options.tripId,
  );
  options.assertActive?.();
  if (search.matchesNothing) {
    return {
      items: [],
      next_cursor: null,
      offline: true,
      projectionCompleteness: completeness,
      total: 0,
    };
  }

  const scopeParameters = [options.accountNamespace, options.tripId];
  const boundaryParameters = keysetParameters(boundary);
  const filtered = filterPredicate(filter, 'passenger');
  let countSql: string;
  let countParameters: readonly (number | string)[];
  let rowsSql: string;
  let rowParameters: readonly (number | string)[];

  if (search.ftsQuery) {
    countSql = `SELECT COUNT(*) AS count
      FROM coordinator_passengers_fts
      JOIN coordinator_passengers AS passenger
        ON passenger.rowid = coordinator_passengers_fts.rowid
     WHERE coordinator_passengers_fts MATCH ?
       AND passenger.account_namespace = ? AND passenger.trip_id = ?${filtered}`;
    countParameters = [search.ftsQuery, ...scopeParameters];
    rowsSql = `SELECT passenger.id, passenger.display_name, passenger.employee_code,
             passenger.attendance_status, passenger.room_number,
             passenger.meal_preference, passenger.has_alert
        FROM coordinator_passengers_fts
        JOIN coordinator_passengers AS passenger
          ON passenger.rowid = coordinator_passengers_fts.rowid
       WHERE coordinator_passengers_fts MATCH ?
         AND passenger.account_namespace = ? AND passenger.trip_id = ?${filtered}
         ${keysetPredicate('passenger', boundary)}
       ORDER BY passenger.display_name COLLATE NOCASE, passenger.id
       LIMIT ?`;
    rowParameters = [
      search.ftsQuery,
      ...scopeParameters,
      ...boundaryParameters,
      LOCAL_ROSTER_PAGE_SIZE + 1,
    ];
  } else {
    countSql = `SELECT COUNT(*) AS count
      FROM coordinator_passengers AS passenger
     WHERE passenger.account_namespace = ? AND passenger.trip_id = ?${filtered}`;
    countParameters = scopeParameters;
    rowsSql = `SELECT passenger.id, passenger.display_name, passenger.employee_code,
             passenger.attendance_status, passenger.room_number,
             passenger.meal_preference, passenger.has_alert
        FROM coordinator_passengers AS passenger
       WHERE passenger.account_namespace = ? AND passenger.trip_id = ?${filtered}
         ${keysetPredicate('passenger', boundary)}
       ORDER BY passenger.display_name COLLATE NOCASE, passenger.id
       LIMIT ?`;
    rowParameters = [
      ...scopeParameters,
      ...boundaryParameters,
      LOCAL_ROSTER_PAGE_SIZE + 1,
    ];
  }

  const count = await options.database.getFirstAsync<{ count: number }>(
    countSql,
    ...countParameters,
  );
  options.assertActive?.();
  const total = count?.count;
  if (typeof total !== 'number' || !Number.isSafeInteger(total) || total < 0) {
    throw new Error('The offline roster count was invalid.');
  }
  const rows = await options.database.getAllAsync<RosterRow>(rowsSql, ...rowParameters);
  options.assertActive?.();
  const hasMore = rows.length > LOCAL_ROSTER_PAGE_SIZE;
  const pageRows = rows.slice(0, LOCAL_ROSTER_PAGE_SIZE);
  let nextCursor: string | null = null;
  if (hasMore) {
    const last = pageRows.at(-1);
    if (!last) throw new Error('The offline roster page boundary was invalid.');
    nextCursor = await createCursor({
      accountNamespace: options.accountNamespace,
      boundary: {
        last_display_name: last.display_name,
        last_passenger_id: last.id,
      },
      createToken: options.createCursorToken ?? Crypto.randomUUID,
      database: options.database,
      filter,
      nowMs,
      searchKey: search.searchKey,
      tripId: options.tripId,
    });
    options.assertActive?.();
  }

  return {
    items: pageRows.map((item) => ({ ...item, has_alert: item.has_alert === 1 })),
    next_cursor: nextCursor,
    offline: true,
    projectionCompleteness: completeness,
    total,
  };
}
