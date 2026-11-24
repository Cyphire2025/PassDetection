import {
  OWNER_USER_ID_INDEX,
  PENDING_ATTENDANCE_STORE,
  REJECTED_ATTENDANCE_STORE,
} from "./browser-offline-database";

export const PENDING_STORE_NAME = PENDING_ATTENDANCE_STORE;

export const REJECTED_STORE_NAME = REJECTED_ATTENDANCE_STORE;

export const OWNER_INDEX = OWNER_USER_ID_INDEX;

export async function readAllUnknown(db: IDBDatabase, storeName: string) {
  const store = db.transaction(storeName, "readonly").objectStore(storeName);
  return requestToPromise<Record<string, unknown>[]>(store.getAll());
}

export function requestToPromise<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function transactionToPromise(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(
      transaction.error ?? new Error("Offline scan transaction failed."),
    );
    transaction.onabort = () => reject(
      transaction.error ?? new Error("Offline scan transaction was aborted."),
    );
  });
}
