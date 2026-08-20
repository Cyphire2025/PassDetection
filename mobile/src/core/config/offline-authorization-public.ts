/**
 * Public verification profile for development builds.
 *
 * The matching private key exists only on the production backend. These
 * values are intentionally safe to embed in the application bundle and may
 * be overridden by EXPO_PUBLIC_* build variables during a controlled key
 * rotation.
 */
export const DEFAULT_OFFLINE_AUTHORIZATION_ISSUER =
  'passdetection-mobile-offline';

export const DEFAULT_OFFLINE_AUTHORIZATION_AUDIENCE = 'gc-mobile-offline';

export const DEFAULT_OFFLINE_AUTHORIZATION_PUBLIC_KEYS_JSON =
  '{"dev-20260820-f6b34c61":"EvvYtWXYgnKK1znyJHucbeQK5VFvJA8oG5Uwkuv4pFE"}';
