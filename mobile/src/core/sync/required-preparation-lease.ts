let activeSessionId: string | null = null;

/**
 * A freshly authenticated session has one owner for its initial network and
 * offline preparation. Runtime connectivity/push refreshes yield until that
 * owner finishes, preventing duplicate manifests and local writes at login.
 */
export function beginRequiredPreparation(sessionId: string): void {
  activeSessionId = sessionId;
}

export function completeRequiredPreparation(sessionId: string): void {
  if (activeSessionId === sessionId) activeSessionId = null;
}

export function cancelRequiredPreparation(sessionId?: string): void {
  if (!sessionId || activeSessionId === sessionId) activeSessionId = null;
}

export function isRequiredPreparationActive(sessionId: string): boolean {
  return activeSessionId === sessionId;
}
