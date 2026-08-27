import {
  BrowserOfflineAuthorizationError,
  checkBrowserOfflineReadiness,
  refreshBrowserOfflineAuthorization,
  type BrowserOfflineReadinessEvidence,
} from "./browser-offline-authorization";

export const BROWSER_OFFLINE_READINESS_RECHECK_MS = 30_000;
const MINIMUM_READINESS_RECHECK_MS = 250;

export type BrowserOfflineReadinessState =
  | Readonly<{
      groupId: string;
      sessionId: string | null;
      status: "checking";
    }>
  | Readonly<{
      checkedAt: string;
      groupId: string;
      sessionId: string | null;
      status: "ready";
      validUntil: string;
    }>
  | Readonly<{
      code: BrowserOfflineAuthorizationError["code"] | "READINESS_CHECK_FAILED";
      groupId: string;
      sessionId: string | null;
      status: "unavailable";
    }>;

type ReadinessDependencies = Readonly<{
  check: typeof checkBrowserOfflineReadiness;
  refresh: typeof refreshBrowserOfflineAuthorization;
}>;

const defaultDependencies: ReadinessDependencies = {
  check: checkBrowserOfflineReadiness,
  refresh: refreshBrowserOfflineAuthorization,
};

/**
 * Resolves the locally enforceable state. An online refresh is best effort:
 * a transient network failure must not discard an otherwise valid cached,
 * signed authorization, while local verification remains authoritative.
 */
export async function resolveBrowserOfflineReadiness({
  dependencies = defaultDependencies,
  groupId,
  refreshOnline,
  sessionId,
  signal,
}: Readonly<{
  dependencies?: ReadinessDependencies;
  groupId: string;
  refreshOnline: boolean;
  sessionId: string | null;
  signal?: AbortSignal;
}>): Promise<Exclude<BrowserOfflineReadinessState, { status: "checking" }>> {
  if (refreshOnline) {
    try {
      await dependencies.refresh(groupId, signal);
    } catch {
      if (signal?.aborted) throw new DOMException("Readiness check aborted", "AbortError");
      // Fall through to the locally stored signed authorization. Network
      // reachability alone is neither readiness proof nor a reason to erase it.
    }
  }

  if (signal?.aborted) throw new DOMException("Readiness check aborted", "AbortError");
  try {
    const evidence = await dependencies.check({ groupId, sessionId });
    if (signal?.aborted) throw new DOMException("Readiness check aborted", "AbortError");
    return {
      ...evidence,
      status: "ready",
    };
  } catch (error) {
    if (signal?.aborted) throw new DOMException("Readiness check aborted", "AbortError");
    return {
      code: error instanceof BrowserOfflineAuthorizationError
        ? error.code
        : "READINESS_CHECK_FAILED",
      groupId,
      sessionId,
      status: "unavailable",
    };
  }
}

/**
 * Uses the trusted-time evidence duration rather than the mutable device wall
 * clock. Readiness is rechecked at least every 30 seconds and just after the
 * earliest authorization, runtime, or activity expiry.
 */
export function browserOfflineReadinessRecheckDelay(
  evidence: BrowserOfflineReadinessEvidence,
): number {
  const checkedAt = Date.parse(evidence.checkedAt);
  const validUntil = Date.parse(evidence.validUntil);
  if (!Number.isFinite(checkedAt) || !Number.isFinite(validUntil)) {
    return MINIMUM_READINESS_RECHECK_MS;
  }
  return Math.max(
    MINIMUM_READINESS_RECHECK_MS,
    Math.min(
      BROWSER_OFFLINE_READINESS_RECHECK_MS,
      validUntil - checkedAt + MINIMUM_READINESS_RECHECK_MS,
    ),
  );
}

export function browserOfflineReadinessAllowsCapture(
  isOnline: boolean,
  readiness: BrowserOfflineReadinessState,
): boolean {
  return isOnline || readiness.status === "ready";
}
