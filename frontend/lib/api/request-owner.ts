import type { AxiosAdapter, AxiosRequestConfig, InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/stores/auth.store";
import { privateAuthorityKey } from "@/features/auth/services/session-continuity";

export interface OwnerBoundRequestConfig extends AxiosRequestConfig {
  expectedOwnerUserId?: string;
  expectedAuthorityKey?: string;
}

export class RequestOwnerChangedError extends Error {
  readonly code = "AUTH_REQUEST_OWNER_CHANGED";

  constructor() {
    super("The signed-in account changed. Sign back in to the original account before retrying.");
    this.name = "RequestOwnerChangedError";
  }
}

export function ownerBoundRequestConfig(ownerUserId: string | undefined): OwnerBoundRequestConfig {
  if (ownerUserId === undefined) return {};
  const user = useAuthStore.getState().user;
  return {
    expectedOwnerUserId: ownerUserId,
    ...(user?.id === ownerUserId ? { expectedAuthorityKey: privateAuthorityKey(user) } : {}),
  };
}

/** Preserve the initiating staff actor across a private operation's async steps. */
export function capturePrivateOperationOwner() {
  const ownerUserId = useAuthStore.getState().user?.id;
  if (!ownerUserId) throw new RequestOwnerChangedError();
  const requestConfig = ownerBoundRequestConfig(ownerUserId);
  return { requestConfig, assertCurrent: () => assertRequestOwner(requestConfig) };
}

/** Capture staff identity once; auth bootstrap and traveller proofs own their identity. */
export function capturePrivateRequestOwner(config: OwnerBoundRequestConfig) {
  if (config.expectedOwnerUserId !== undefined) {
    if (config.expectedAuthorityKey === undefined) {
      config.expectedAuthorityKey = ownerBoundRequestConfig(config.expectedOwnerUserId).expectedAuthorityKey;
    }
    return;
  }
  const path = config.url?.split(/[?#]/, 1)[0] ?? "";
  if (!path.startsWith("/api/v1/")) return;
  if (/^\/api\/v1\/(?:returning|public-drafts|health)(?:\/|$)/.test(path)) return;
  if (path.startsWith("/api/v1/auth/")
    && !/^\/api\/v1\/auth\/(?:access-level|password\/change|mfa\/(?:step-up|recovery-codes\/regenerate))(?:\/|$)/.test(path)) return;
  if (/^\/api\/v1\/(?:passports\/upload|upload-links\/token)(?:\/|$)/.test(path)) return;
  if (/^\/api\/v1\/passports\/[^/]+\/(?:client-submit|contact-otp)(?:\/|$)/.test(path)) return;
  const ownerUserId = useAuthStore.getState().user?.id;
  if (ownerUserId) Object.assign(config, ownerBoundRequestConfig(ownerUserId));
}

export function assertRequestOwner(config: OwnerBoundRequestConfig) {
  if (config.expectedOwnerUserId !== undefined
    && useAuthStore.getState().user?.id !== config.expectedOwnerUserId) {
    throw new RequestOwnerChangedError();
  }
  if (config.expectedAuthorityKey !== undefined
    && privateAuthorityKey(useAuthStore.getState().user) !== config.expectedAuthorityKey) {
    throw new RequestOwnerChangedError();
  }
}

/** Guard after async interceptors and keep stale private responses out of callers. */
export function ownerBoundAdapter(delegate: AxiosAdapter): AxiosAdapter {
  return async (config: InternalAxiosRequestConfig & OwnerBoundRequestConfig) => {
    const owner = config.expectedOwnerUserId;
    if (owner === undefined) return delegate(config);
    assertRequestOwner(config);
    const controller = new AbortController();
    const callerSignal = config.signal;
    const cancelFromCaller = () => controller.abort();
    const unsubscribe = useAuthStore.subscribe((state) => {
      if (state.user?.id !== owner || (config.expectedAuthorityKey !== undefined
        && privateAuthorityKey(state.user) !== config.expectedAuthorityKey)) controller.abort();
    });
    callerSignal?.addEventListener?.("abort", cancelFromCaller);
    if (callerSignal?.aborted) controller.abort();
    config.signal = controller.signal;
    // This is a mismatch precondition, not an authorization credential. The
    // backend still derives the actual actor from its authenticated session.
    config.headers.set("X-Expected-Actor-Id", owner);
    try {
      assertRequestOwner(config);
      const response = await delegate(config);
      assertRequestOwner(config);
      return response;
    } catch (error) {
      assertRequestOwner(config);
      throw error;
    } finally {
      unsubscribe();
      callerSignal?.removeEventListener?.("abort", cancelFromCaller);
      config.signal = callerSignal;
    }
  };
}
