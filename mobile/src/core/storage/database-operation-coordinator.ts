import type { SQLiteDatabase } from 'expo-sqlite';

export type DatabaseOperationCoordinator = Readonly<{
  run: <T>(task: () => PromiseLike<T> | T) => Promise<T>;
  stop: () => void;
  wait: () => Promise<void>;
}>;

function databaseClosingError(): Error {
  return new Error('The offline database is closing and cannot start another operation.');
}

/**
 * Tracks every promise-based operation issued through the shared account connection.
 * Expo SQLite convenience methods prepare and finalize native statements across
 * multiple asynchronous native calls. Closing between those calls can race a
 * statement finalizer and abort Android, so logout first stops admission and then
 * waits until every accepted operation has fully finalized.
 */
export function coordinateDatabaseOperations(): DatabaseOperationCoordinator {
  let acceptingOperations = true;
  let inFlightOperations = 0;
  const drainWaiters = new Set<() => void>();

  const finishOperation = (): void => {
    inFlightOperations = Math.max(0, inFlightOperations - 1);
    if (inFlightOperations !== 0) return;
    for (const resolve of drainWaiters) resolve();
    drainWaiters.clear();
  };

  return {
    run: <T>(task: () => PromiseLike<T> | T): Promise<T> => {
      if (!acceptingOperations) return Promise.reject(databaseClosingError());
      inFlightOperations += 1;
      let result: Promise<T>;
      try {
        result = Promise.resolve(task());
      } catch (error) {
        finishOperation();
        return Promise.reject(error);
      }
      return result.finally(finishOperation);
    },
    stop: () => {
      acceptingOperations = false;
    },
    wait: () => {
      if (inFlightOperations === 0) return Promise.resolve();
      return new Promise<void>((resolve) => drainWaiters.add(resolve));
    },
  };
}

const ESCAPING_DATABASE_METHODS = new Set<PropertyKey>([
  'closeAsync',
  'closeSync',
  'createSessionAsync',
  'createSessionSync',
  'getEachAsync',
  'getEachSync',
  'prepareAsync',
  'prepareSync',
  'sql',
]);

/**
 * Exposes normal promise-returning query helpers while retaining lifecycle
 * ownership. Prepared statements, async iterators, sessions, and the native handle
 * could outlive a tracked call, so feature code must use scoped repository helpers.
 */
export function guardAccountDatabase(
  database: SQLiteDatabase,
  operations: DatabaseOperationCoordinator,
): SQLiteDatabase {
  const methodCache = new Map<PropertyKey, unknown>();
  return new Proxy(database, {
    get(target, property) {
      if (property === 'nativeDatabase') {
        throw new Error('The native account database handle is lifecycle-managed.');
      }
      const value: unknown = Reflect.get(target, property, target);
      if (typeof value !== 'function') return value;
      if (methodCache.has(property)) return methodCache.get(property);

      let guarded: unknown;
      if (
        ESCAPING_DATABASE_METHODS.has(property)
        || (typeof property === 'string' && property.endsWith('Sync'))
      ) {
        guarded = () => {
          throw new Error('Unscoped account database operations are not supported.');
        };
      } else if (typeof property === 'string' && property.endsWith('Async')) {
        guarded = (...parameters: unknown[]) => operations.run(() => (
          Reflect.apply(value, target, parameters) as PromiseLike<unknown>
        ));
      } else {
        guarded = (...parameters: unknown[]) => Reflect.apply(value, target, parameters);
      }
      methodCache.set(property, guarded);
      return guarded;
    },
  });
}
