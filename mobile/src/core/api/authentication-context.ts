import {
  isAuthenticationEpochCurrent,
  type AuthenticationSnapshot,
} from '@/core/auth/session-store';

import { ApiError } from './api-error';

export function authenticationContextChanged(): ApiError {
  return new ApiError(
    'The active account changed while this request was running.',
    409,
    'AUTH_CONTEXT_CHANGED',
    null,
  );
}

export function assertAuthenticationContextCurrent(
  authentication: AuthenticationSnapshot | null,
): void {
  if (authentication && !isAuthenticationEpochCurrent(authentication.epoch)) {
    throw authenticationContextChanged();
  }
}
