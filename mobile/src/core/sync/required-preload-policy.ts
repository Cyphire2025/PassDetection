import type { MobileSession } from '@/core/auth/types';

/**
 * Identifies the authenticated device session that owns one preparation run.
 *
 * Profile refreshes intentionally replace the in-memory session object. They must not restart
 * required preparation, while a real account or device-session change must start a new run.
 */
export function requiredPreparationRunKey(session: MobileSession | null): string | null {
  if (!session) return null;
  return [
    session.principal.agencyId,
    session.principal.id,
    session.sessionId,
  ].join(':');
}
