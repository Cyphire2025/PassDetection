import { TOKEN_PATTERN, isUuid, isValidViewState, type PassportDetailNavigationState } from "./passport-navigation-routes";

export interface StoredPassportNavigationContext
  extends PassportDetailNavigationState {
  version: 1;
  token: string;
  userId: string;
  orderedSubmissionIds: string[];
  createdAt: number;
}

const STORAGE_PREFIX = "passdetection:passport-navigation:";

const CONTEXT_TTL_MS = 12 * 60 * 60 * 1000;

const MAX_NAVIGATION_ITEMS = 10_000;

export function storePassportNavigationContext(
  context: Omit<StoredPassportNavigationContext, "version" | "createdAt">,
) {
  if (
    typeof window === "undefined"
    || !TOKEN_PATTERN.test(context.token)
    || !isUuid(context.userId)
    || !isUuid(context.groupId)
    || context.orderedSubmissionIds.length > MAX_NAVIGATION_ITEMS
    || context.orderedSubmissionIds.some((id) => !isUuid(id))
  ) {
    return false;
  }

  const stored: StoredPassportNavigationContext = {
    ...context,
    version: 1,
    createdAt: Date.now(),
    orderedSubmissionIds: [...context.orderedSubmissionIds],
  };
  try {
    window.sessionStorage.setItem(
      navigationStorageKey(context.userId, context.token),
      JSON.stringify(stored),
    );
    pruneExpiredNavigationContexts(context.userId, context.token);
    return true;
  } catch {
    return false;
  }
}

export function readPassportNavigationContext({
  token,
  userId,
  groupId,
}: {
  token: string | null;
  userId: string | null | undefined;
  groupId: string;
}): StoredPassportNavigationContext | null {
  if (
    typeof window === "undefined"
    || !token
    || !userId
    || !TOKEN_PATTERN.test(token)
    || !isUuid(userId)
    || !isUuid(groupId)
  ) {
    return null;
  }

  const key = navigationStorageKey(userId, token);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPassportNavigationContext>;
    if (
      parsed.version !== 1
      || parsed.token !== token
      || parsed.userId !== userId
      || parsed.groupId !== groupId
      || typeof parsed.createdAt !== "number"
      || parsed.createdAt > Date.now() + 60_000
      || Date.now() - parsed.createdAt > CONTEXT_TTL_MS
      || !Array.isArray(parsed.orderedSubmissionIds)
      || parsed.orderedSubmissionIds.length > MAX_NAVIGATION_ITEMS
      || parsed.orderedSubmissionIds.some((id) => !isUuid(id))
      || !isValidViewState(parsed.viewState)
      || typeof parsed.includeDeleted !== "boolean"
    ) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return parsed as StoredPassportNavigationContext;
  } catch {
    // Storage access and cleanup can both be denied by browser privacy settings.
    try { window.sessionStorage.removeItem(key); } catch { /* Use server navigation instead. */ }
    return null;
  }
}

function navigationStorageKey(userId: string, token: string) {
  return `${STORAGE_PREFIX}${userId}:${token}`;
}

function pruneExpiredNavigationContexts(userId: string, activeToken: string) {
  const prefix = `${STORAGE_PREFIX}${userId}:`;
  const expiredKeys: string[] = [];
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index);
    if (!key?.startsWith(prefix) || key.endsWith(activeToken)) continue;
    try {
      const parsed = JSON.parse(
        window.sessionStorage.getItem(key) ?? "",
      ) as { createdAt?: unknown };
      if (
        typeof parsed.createdAt !== "number"
        || Date.now() - parsed.createdAt > CONTEXT_TTL_MS
      ) {
        expiredKeys.push(key);
      }
    } catch {
      expiredKeys.push(key);
    }
  }
  expiredKeys.forEach((key) => window.sessionStorage.removeItem(key));
}
