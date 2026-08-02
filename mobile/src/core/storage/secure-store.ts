import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';

const KEY_PREFIX = 'gc.v1';
const NAMESPACE_INDEX_KEY = `${KEY_PREFIX}.namespaces`;
const INSTALLATION_ID_KEY = `${KEY_PREFIX}.installation-id`;
const ACTIVE_NAMESPACE_KEY = `${KEY_PREFIX}.active-namespace`;
const INSTALL_MARKER = new File(Paths.document, '.gc-install-marker-v1');

type SecretKind = 'refresh' | 'database-key' | 'vault-key';

function assertNamespace(namespace: string): void {
  if (!/^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(namespace)) {
    throw new Error('Invalid account namespace.');
  }
}

function keyFor(namespace: string, kind: SecretKind): string {
  assertNamespace(namespace);
  return `${KEY_PREFIX}.${namespace}.${kind}`;
}

async function readNamespaces(): Promise<string[]> {
  const encoded = await SecureStore.getItemAsync(NAMESPACE_INDEX_KEY);
  if (!encoded) return [];

  try {
    const parsed: unknown = JSON.parse(encoded);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (value): value is string =>
        typeof value === 'string' && /^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(value),
    );
  } catch {
    return [];
  }
}

async function trackNamespace(namespace: string): Promise<void> {
  assertNamespace(namespace);
  const namespaces = new Set(await readNamespaces());
  namespaces.add(namespace);
  await SecureStore.setItemAsync(NAMESPACE_INDEX_KEY, JSON.stringify([...namespaces]), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function initializeFreshInstallGuard(): Promise<void> {
  if (INSTALL_MARKER.exists) return;

  for (const namespace of await readNamespaces()) {
    await Promise.all(
      (['refresh', 'database-key', 'vault-key'] as const).map((kind) =>
        SecureStore.deleteItemAsync(keyFor(namespace, kind)),
      ),
    );
  }

  await SecureStore.deleteItemAsync(NAMESPACE_INDEX_KEY);
  await SecureStore.deleteItemAsync(INSTALLATION_ID_KEY);
  await SecureStore.deleteItemAsync(ACTIVE_NAMESPACE_KEY);

  const parent = new Directory(Paths.document);
  if (!parent.exists) parent.create({ idempotent: true, intermediates: true });
  INSTALL_MARKER.create({ overwrite: true, intermediates: true });
  INSTALL_MARKER.write('group-companion-v1');
}

export async function getInstallationId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(INSTALLATION_ID_KEY);
  if (existing) return existing;

  const created = Crypto.randomUUID();
  await SecureStore.setItemAsync(INSTALLATION_ID_KEY, created, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
  return created;
}

export async function setRefreshToken(namespace: string, token: string): Promise<void> {
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(keyFor(namespace, 'refresh'), token, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function setActiveNamespace(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(ACTIVE_NAMESPACE_KEY, namespace, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function getActiveNamespace(): Promise<string | null> {
  const namespace = await SecureStore.getItemAsync(ACTIVE_NAMESPACE_KEY);
  if (!namespace || !/^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(namespace)) return null;
  return namespace;
}

export async function getRefreshToken(namespace: string): Promise<string | null> {
  return SecureStore.getItemAsync(keyFor(namespace, 'refresh'));
}

export async function getOrCreateSecret(
  namespace: string,
  kind: Extract<SecretKind, 'database-key' | 'vault-key'>,
): Promise<string> {
  const storageKey = keyFor(namespace, kind);
  const existing = await SecureStore.getItemAsync(storageKey);
  if (existing && /^[0-9a-f]{64}$/i.test(existing)) return existing;

  const bytes = await Crypto.getRandomBytesAsync(32);
  const created = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  await trackNamespace(namespace);
  await SecureStore.setItemAsync(storageKey, created, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
  return created;
}

export async function clearNamespaceSecrets(namespace: string): Promise<void> {
  assertNamespace(namespace);
  await Promise.all(
    (['refresh', 'database-key', 'vault-key'] as const).map((kind) =>
      SecureStore.deleteItemAsync(keyFor(namespace, kind)),
    ),
  );

  const remaining = (await readNamespaces()).filter((value) => value !== namespace);
  await SecureStore.setItemAsync(NAMESPACE_INDEX_KEY, JSON.stringify(remaining), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });

  if ((await getActiveNamespace()) === namespace) {
    await SecureStore.deleteItemAsync(ACTIVE_NAMESPACE_KEY);
  }
}
