import { ApiError } from './api-error';

const MAX_DIRECT_OBJECT_URL_LENGTH = 8_192;
const MAX_PRESIGNED_LIFETIME_SECONDS = 900;

export type ValidatedDirectObjectRedirect = Readonly<{
  expiresAtMs: number;
  url: string;
}>;

function invalidRedirect(): never {
  throw new ApiError(
    'The photo delivery redirect was invalid.',
    502,
    'PHOTO_DELIVERY_REDIRECT_INVALID',
    null,
  );
}

/**
 * Validates the one opaque provider hop emitted by the authenticated API.
 * Only a bounded HTTPS URL on a different origin and the API's separately
 * attested, short expiry are accepted. Provider query fields are never parsed.
 * The returned URL is intentionally ephemeral and must never be logged or
 * persisted.
 */
export function validateDirectObjectRedirect(
  apiUrl: string,
  location: string | null,
  expiresAtHeader: string | null,
): ValidatedDirectObjectRedirect {
  if (!location || location.length > MAX_DIRECT_OBJECT_URL_LENGTH) invalidRedirect();
  let candidate: URL;
  let api: URL;
  try {
    candidate = new URL(location);
    api = new URL(apiUrl);
  } catch {
    return invalidRedirect();
  }
  const expiresAtMs = Date.parse(expiresAtHeader ?? '');
  const remainingMs = expiresAtMs - Date.now();
  if (
    candidate.protocol !== 'https:'
    || candidate.origin === api.origin
    || candidate.username !== ''
    || candidate.password !== ''
    || candidate.hash !== ''
    || !expiresAtHeader
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(expiresAtHeader)
    || !Number.isFinite(expiresAtMs)
    || remainingMs <= 0
    || remainingMs > MAX_PRESIGNED_LIFETIME_SECONDS * 1_000
  ) invalidRedirect();
  return Object.freeze({ expiresAtMs, url: candidate.toString() });
}
