interface SessionStorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

interface PublicUploadSessionOptions {
  storage?: SessionStorageLike;
  randomId?: () => string;
}

const inMemorySessions = new Map<string, string>();

function storageKey(groupToken: string) {
  return `gct:public-upload-bootstrap:${groupToken}`;
}

function defaultRandomId() {
  if (
    typeof crypto !== "undefined"
    && typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function getOrCreatePublicUploadSessionId(
  groupToken: string,
  options: PublicUploadSessionOptions = {},
) {
  const createSessionId = () => `bootstrap-${(options.randomId ?? defaultRandomId)()}`;
  try {
    const storage = options.storage ?? window.sessionStorage;
    const key = storageKey(groupToken);
    const existing = storage.getItem(key);
    if (existing && /^[A-Za-z0-9._:-]{8,128}$/.test(existing)) {
      return existing;
    }
    const created = createSessionId();
    storage.setItem(key, created);
    return created;
  } catch {
    // Some privacy-restricted in-app browsers disable sessionStorage. A
    // stable id for this module instance still keeps the request valid; the
    // server-side shared-network guard remains active.
    const existing = inMemorySessions.get(groupToken);
    if (existing) return existing;
    const created = createSessionId();
    inMemorySessions.set(groupToken, created);
    return created;
  }
}
