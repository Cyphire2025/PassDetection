/** Minimal asynchronous IDB boundary for queue timing tests, not a browser emulator. */
export function attendanceTestDatabase() {
  type Row = Record<string, unknown>;
  const stores = new Map<string, Map<string, Row>>();
  const storeRows = (name: string) => {
    let rows = stores.get(name);
    if (!rows) { rows = new Map(); stores.set(name, rows); }
    return rows;
  };
  let afterWrite: ((store: string, row: Row) => void) | undefined;
  let afterRead: ((store: string, id: string) => void) | undefined;
  const database = {
    close() {},
    transaction() {
      let pending = 0;
      let timer: ReturnType<typeof setTimeout>;
      const transaction = { oncomplete: null as (() => void) | null, objectStore };
      function completeLater() {
        clearTimeout(timer);
        timer = setTimeout(() => { if (pending === 0) transaction.oncomplete?.(); }, 0);
      }
      function request<T>(action: () => T) {
        pending++;
        const operation = { result: undefined as T | undefined, onsuccess: null as (() => void) | null };
        queueMicrotask(() => {
          operation.result = action();
          operation.onsuccess?.();
          pending--;
          completeLater();
        });
        return operation;
      }
      function objectStore(name: string) {
        const rows = storeRows(name);
        return {
          get: (id: string) => request(() => {
            const value = rows.has(id) ? { ...rows.get(id) } : undefined;
            afterRead?.(name, id);
            return value;
          }),
          getAll: () => request(() => [...rows.values()].map((row) => ({ ...row }))),
          put: (row: Row) => request(() => {
            rows.set(String(row.id), { ...row });
            afterWrite?.(name, row);
            return row.id;
          }),
          delete: (id: string) => request(() => rows.delete(id)),
          index: () => ({ getAll: (owner: string) => request(() => [...rows.values()]
            .filter((row) => row.ownerUserId === owner).map((row) => ({ ...row }))) }),
        };
      }
      completeLater();
      return transaction;
    },
  };
  return {
    database: database as unknown as IDBDatabase,
    rows: storeRows,
    onWrite(callback: typeof afterWrite) { afterWrite = callback; },
    onRead(callback: typeof afterRead) { afterRead = callback; },
  };
}
