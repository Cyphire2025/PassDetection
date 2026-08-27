import * as Crypto from 'expo-crypto';
import { fetch as expoFetch } from 'expo/fetch';

import {
  captureAuthenticationSnapshot,
} from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';

import { handleAccessDenied } from './access-denied-handler';
import { ApiError } from './api-error';
import { authorizedDocumentUrl } from './api-url';
import { assertAuthenticationContextCurrent } from './authentication-context';
import { validateDirectObjectRedirect } from './direct-object-redirect';

export type AuthorizedDownloadStreamResponse = Readonly<{
  status: number;
  headers: Readonly<Record<string, string>>;
  body: ReadableStream<Uint8Array>;
}>;

export type AuthorizedDownloadStreamOptions = Readonly<{
  maximumBytes: number;
  rangeStart: number;
  rangeEndInclusive: number;
  requestRange: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
}>;

/**
 * Executes a short-lived authorized download while the caller consumes the
 * native Expo response stream. Authentication and timeout fences remain
 * active through the final byte. There is deliberately no plaintext-file
 * fallback when the native runtime cannot expose a stream.
 */
export async function withAuthorizedDownloadStream<T>(
  path: string,
  downloadToken: string,
  options: AuthorizedDownloadStreamOptions,
  consume: (
    response: AuthorizedDownloadStreamResponse,
    assertAuthenticationCurrent: () => void,
  ) => Promise<T>,
): Promise<T> {
  if (isDemoMode()) {
    throw new ApiError(
      'Photo downloads are disabled in the local emulator demo.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const authentication = captureAuthenticationSnapshot();
  const token = authentication.accessToken;
  if (!token) throw new ApiError('Authentication is required.', 401, 'AUTH_REQUIRED', null);
  if (!/^[A-Za-z0-9._~-]{32,4096}$/.test(downloadToken)) {
    throw new ApiError(
      'The download authorization was invalid.',
      400,
      'INVALID_DOWNLOAD_TOKEN',
      null,
    );
  }
  if (
    !Number.isSafeInteger(options.maximumBytes)
    || options.maximumBytes < 1
    || !Number.isSafeInteger(options.rangeStart)
    || options.rangeStart < 0
    || !Number.isSafeInteger(options.rangeEndInclusive)
    || options.rangeEndInclusive < options.rangeStart
    || options.rangeEndInclusive - options.rangeStart + 1 !== options.maximumBytes
    || (!options.requestRange && options.rangeStart !== 0)
  ) {
    throw new ApiError('The download range was invalid.', 400, 'INVALID_DOWNLOAD_RANGE', null);
  }
  const headers: Record<string, string> = {
    Accept: 'image/jpeg,image/png,image/webp',
    Authorization: `Bearer ${token}`,
    'Cache-Control': 'no-store',
    'X-GC-Download-Token': downloadToken,
    'X-Request-ID': Crypto.randomUUID(),
  };
  if (options.requestRange) {
    headers.Range = `bytes=${options.rangeStart}-${options.rangeEndInclusive}`;
  }
  const timeout = AbortSignal.timeout(options.timeoutMs ?? 60_000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const apiUrl = authorizedDocumentUrl(path);
  const assertCurrent = () => {
    if (options.signal?.aborted) {
      throw options.signal.reason instanceof Error
        ? options.signal.reason
        : new DOMException('The photo download was cancelled.', 'AbortError');
    }
    assertAuthenticationContextCurrent(authentication);
    if (timeout.aborted) {
      throw new ApiError(
        'The photo delivery request timed out.',
        408,
        'PHOTO_DELIVERY_TIMEOUT',
        null,
      );
    }
  };
  let response: Awaited<ReturnType<typeof expoFetch>>;
  let providerHop = false;
  try {
    response = await expoFetch(apiUrl, {
      method: 'GET',
      headers,
      // Manual mode is implemented natively by Expo with redirects disabled,
      // allowing Location to be validated before any cross-origin request.
      redirect: 'manual',
      signal,
    });
  } catch (error) {
    assertCurrent();
    throw error;
  }
  assertCurrent();
  if (response.status === 307) {
    const location = response.headers.get('location');
    await response.body?.cancel().catch(() => undefined);
    const target = validateDirectObjectRedirect(
      apiUrl,
      location,
      response.headers.get('x-gc-media-expires-at'),
    ).url;
    const directHeaders: Record<string, string> = {
      Accept: 'image/jpeg,image/png,image/webp',
      'Cache-Control': 'no-store',
    };
    if (options.requestRange) {
      directHeaders.Range = `bytes=${options.rangeStart}-${options.rangeEndInclusive}`;
    }
    assertCurrent();
    providerHop = true;
    try {
      // This is a separate request with a freshly constructed allowlisted
      // header set. Bearer, grant and request-correlation headers cannot cross
      // the API/provider origin boundary. The signed URL remains in memory only.
      response = await expoFetch(target, {
        method: 'GET',
        credentials: 'omit',
        headers: directHeaders,
        redirect: 'error',
        signal,
      });
    } catch (error) {
      assertCurrent();
      throw error;
    }
    assertCurrent();
  }
  // Redirects are permitted only on the authenticated API response above.
  // A provider redirect (or any non-307 API redirect) is never followed.
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError(
      'The photo delivery redirect was invalid.',
      502,
      'PHOTO_DELIVERY_REDIRECT_INVALID',
      null,
    );
  }
  if (providerHop && (response.status === 401 || response.status === 403)) {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError(
      'The short-lived photo delivery URL expired or was denied.',
      503,
      'PHOTO_DELIVERY_AUTH_EXPIRED',
      null,
    );
  }
  if (!providerHop && response.status === 401) {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError(
      'The photo authorization expired and will be refreshed.',
      401,
      'DOWNLOAD_AUTH_EXPIRED',
      null,
    );
  }
  if (response.status < 200 || response.status >= 300) {
    await response.body?.cancel().catch(() => undefined);
    if (!providerHop) await handleAccessDenied(path, response.status);
    assertCurrent();
    throw new ApiError(
      'The server could not complete this photo download.',
      response.status,
      `HTTP_${response.status}`,
      null,
    );
  }
  if (!response.body || typeof response.body.getReader !== 'function') {
    await response.body?.cancel().catch(() => undefined);
    throw new ApiError(
      'Native encrypted photo streaming is unavailable on this device.',
      503,
      'NATIVE_STREAM_UNAVAILABLE',
      null,
    );
  }
  const responseHeaders: Record<string, string> = {};
  response.headers.forEach((value, key) => {
    responseHeaders[key.toLowerCase()] = value;
  });
  try {
    const result = await consume({
      status: response.status,
      headers: Object.freeze(responseHeaders),
      body: response.body,
    }, assertCurrent);
    assertCurrent();
    return result;
  } catch (error) {
    if (!response.body.locked) await response.body.cancel().catch(() => undefined);
    // Expo rejects an in-flight body read with the request signal's abort
    // reason. Re-enter the shared boundary so an internal deadline is always
    // normalized to the retryable PHOTO_DELIVERY_TIMEOUT contract, while an
    // explicit caller abort or authentication change retains precedence.
    assertCurrent();
    throw error;
  }
}
