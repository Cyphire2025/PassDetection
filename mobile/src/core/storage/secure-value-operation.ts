import type { SecureValueKind } from './secure-store-policy';
import {
  readSecureValueFromBackend,
  writeSecureValueToBackend,
} from './secure-value-backend';

const operationTails = new Map<string, Promise<void>>();

export async function withSecureValueOperation<T>(
  key: string,
  operation: () => Promise<T>,
): Promise<T> {
  const previous = operationTails.get(key) ?? Promise.resolve();
  let release!: () => void;
  const tail = new Promise<void>((resolve) => {
    release = resolve;
  });
  operationTails.set(key, tail);
  await previous;
  try {
    return await operation();
  } finally {
    release();
    if (operationTails.get(key) === tail) operationTails.delete(key);
  }
}

/** Compares and replaces a hardened value atomically with deletion and refresh. */
export function compareAndSetSecureValue(
  key: string,
  kind: SecureValueKind,
  matches: (encoded: string) => boolean,
  replacement: string,
): Promise<boolean> {
  return withSecureValueOperation(key, async () => {
    const encoded = await readSecureValueFromBackend(key, kind);
    if (encoded === null || !matches(encoded)) return false;
    await writeSecureValueToBackend(key, kind, replacement);
    return true;
  });
}
