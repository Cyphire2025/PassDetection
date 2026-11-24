import { useAuthStore } from "@/stores/auth.store";

/** Continuity for an intentional identity operation, not an authorization grant. */
export interface AuthenticationContext {
  ownerUserId: string | null;
  sessionVersion: number;
}

export function captureAuthenticationContext(): AuthenticationContext {
  const { user, sessionVersion } = useAuthStore.getState();
  return { ownerUserId: user?.id ?? null, sessionVersion };
}

export function authenticationContextIsCurrent(context: AuthenticationContext | undefined): boolean {
  if (!context) return false;
  const current = captureAuthenticationContext();
  return current.ownerUserId === context.ownerUserId && current.sessionVersion === context.sessionVersion;
}

/** Abort old identity responses before their delayed headers can replace newer cookies. */
export async function runIdentityOperation<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const authentication = captureAuthenticationContext();
  const controller = new AbortController();
  const unsubscribe = useAuthStore.subscribe(() => {
    if (!authenticationContextIsCurrent(authentication)) controller.abort();
  });
  try {
    const result = await operation(controller.signal);
    if (!authenticationContextIsCurrent(authentication)) {
      throw new Error("Your signed-in account changed. Start this identity operation again.");
    }
    return result;
  } finally {
    unsubscribe();
  }
}
