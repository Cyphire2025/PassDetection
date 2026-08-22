import * as Crypto from 'expo-crypto';
import type { ZodType } from 'zod';

import {
  captureAuthenticationSnapshot,
  currentAccessToken,
  isAuthenticationEpochCurrent,
  type AuthenticationSnapshot,
} from '@/core/auth/session-store';
import { env } from '@/core/config/env';
import { isDemoMode } from '@/core/demo/demo-mode';
import {
  recordMobileMetric,
  type MobileMetricAttributes,
} from '@/core/observability/mobile-observability';

import { ApiError } from './api-error';
import { ApiErrorBodySchema } from './contracts';
import {
  downloadNativeFileBounded,
  NativeFileDownloadTooLargeError,
  type NativeFileDownloadResult,
} from './native-file-download';

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_JSON_BYTES = 2 * 1024 * 1024;
const MAX_ERROR_JSON_BYTES = 64 * 1024;
type ApiMetricOutcome = NonNullable<MobileMetricAttributes['outcome']>;

class ResponseBodyTooLargeError extends Error {
  constructor() {
    super('The response body exceeded its allowed size.');
    this.name = 'ResponseBodyTooLargeError';
  }
}

type RefreshHandler = (snapshot: AuthenticationSnapshot) => Promise<string | null>;
type AccessDeniedHandler = (path: string, status: number) => Promise<void>;
type RefreshOperation = {
  snapshot: AuthenticationSnapshot;
  promise: Promise<string | null>;
};
let refreshHandler: RefreshHandler | null = null;
let accessDeniedHandler: AccessDeniedHandler | null = null;
let refreshInFlight: RefreshOperation | null = null;

export type ApiRequestOptions<T> = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  schema: ZodType<T>;
  authenticated?: boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
  retryAuthentication?: boolean;
  headers?: Readonly<Record<string, string>>;
};

export { ApiError } from './api-error';

export type ApiFileDownloadOptions = Readonly<{
  accept: string;
  destinationPath: string;
  maximumBytes: number;
  retryAuthentication?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
}>;

export function registerRefreshHandler(handler: RefreshHandler): () => void {
  refreshHandler = handler;
  return () => {
    if (refreshHandler === handler) refreshHandler = null;
  };
}

export function registerAccessDeniedHandler(handler: AccessDeniedHandler): () => void {
  accessDeniedHandler = handler;
  return () => {
    if (accessDeniedHandler === handler) accessDeniedHandler = null;
  };
}

async function handleAccessDenied(path: string, status: number): Promise<void> {
  if ((status === 401 || status === 403) && accessDeniedHandler) {
    await accessDeniedHandler(path, status).catch(() => undefined);
  }
}

function assertSafeApiPath(path: string): void {
  if (
    !path.startsWith('/')
    || path.startsWith('//')
    || path.includes('#')
    || path.includes('\\')
    || /[\u0000-\u001f\u007f]/.test(path)
  ) {
    throw new Error('API paths must be root-relative.');
  }
  const pathname = path.split('?', 1)[0] ?? '';
  for (const segment of pathname.split('/').slice(1)) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      throw new Error('API paths must use valid percent encoding.');
    }
    if (
      decoded === '.'
      || decoded === '..'
      || decoded.includes('/')
      || decoded.includes('\\')
      || /[\u0000-\u001f\u007f]/.test(decoded)
    ) {
      throw new Error('API paths must not contain traversal or encoded separators.');
    }
  }
}

function endpointUrl(path: string): string {
  assertSafeApiPath(path);
  return `${env.apiUrl}${path}`;
}

function authorizedDocumentUrl(path: string): string {
  assertSafeApiPath(path);
  const apiBase = new URL(env.apiUrl);
  const parsedPath = new URL(path, apiBase.origin);
  const basePath = apiBase.pathname.replace(/\/$/, '');
  if (
    !path.startsWith('/')
    || path.startsWith('//')
    || parsedPath.origin !== apiBase.origin
    || (!parsedPath.pathname.startsWith(`${basePath}/mobile/`)
      && !parsedPath.pathname.startsWith('/mobile/'))
  ) {
    throw new ApiError('The download path was invalid.', 400, 'INVALID_DOWNLOAD_PATH', null);
  }
  return parsedPath.pathname.startsWith(`${basePath}/mobile/`)
    ? `${apiBase.origin}${parsedPath.pathname}${parsedPath.search}`
    : `${env.apiUrl}${parsedPath.pathname}${parsedPath.search}`;
}

async function nativeFileRequest(options: Readonly<{
  authentication: AuthenticationSnapshot;
  destinationPath: string;
  headers: Readonly<Record<string, string>>;
  maximumBytes: number;
  signal?: AbortSignal;
  timeoutMs: number;
  url: string;
}>): Promise<NativeFileDownloadResult> {
  const timeout = AbortSignal.timeout(options.timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    const response = await downloadNativeFileBounded({
      destinationPath: options.destinationPath,
      headers: options.headers,
      maximumBytes: options.maximumBytes,
      signal,
      timeoutMs: options.timeoutMs,
      url: options.url,
    });
    if (!isAuthenticationEpochCurrent(options.authentication.epoch)) {
      throw authenticationContextChanged();
    }
    return response;
  } catch (error) {
    if (!isAuthenticationEpochCurrent(options.authentication.epoch)) {
      throw authenticationContextChanged();
    }
    if (error instanceof NativeFileDownloadTooLargeError) {
      throw new ApiError(
        'The server returned a file larger than the allowed limit.',
        502,
        'PAYLOAD_TOO_LARGE',
        null,
      );
    }
    throw error;
  }
}

function sameRefreshBoundary(
  first: AuthenticationSnapshot,
  second: AuthenticationSnapshot,
): boolean {
  return first.epoch === second.epoch && first.accessToken === second.accessToken;
}

function authenticationContextChanged(): ApiError {
  return new ApiError(
    'The active account changed while this request was running.',
    409,
    'AUTH_CONTEXT_CHANGED',
    null,
  );
}

function assertAuthenticationContextCurrent(
  authentication: AuthenticationSnapshot | null,
): void {
  if (authentication && !isAuthenticationEpochCurrent(authentication.epoch)) {
    throw authenticationContextChanged();
  }
}

async function refreshAccessToken(snapshot: AuthenticationSnapshot): Promise<string | null> {
  if (!refreshHandler) return null;
  if (!isAuthenticationEpochCurrent(snapshot.epoch)) return null;

  const currentToken = currentAccessToken();
  if (currentToken !== snapshot.accessToken) return currentToken;
  if (refreshInFlight && sameRefreshBoundary(refreshInFlight.snapshot, snapshot)) {
    return refreshInFlight.promise;
  }

  const handler = refreshHandler;
  let operation: RefreshOperation;
  const promise = handler(snapshot)
    .then((token) => {
      if (!isAuthenticationEpochCurrent(snapshot.epoch)) return null;
      return token && currentAccessToken() === token ? token : null;
    })
    .finally(() => {
      if (refreshInFlight === operation) refreshInFlight = null;
    });
  operation = { snapshot, promise };
  refreshInFlight = operation;
  return promise;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value || !/^\d{1,6}$/.test(value)) return null;
  return Number(value);
}

function assertDeclaredJsonLength(response: Response, maximumBytes: number): void {
  const length = response.headers.get('content-length');
  if (length === null) return;
  if (!/^\d+$/.test(length)) throw new Error('The response declared an invalid content length.');
  if (Number(length) > maximumBytes) throw new ResponseBodyTooLargeError();
}

async function readJsonBodyBounded(response: Response, maximumBytes: number): Promise<unknown> {
  assertDeclaredJsonLength(response, maximumBytes);
  const reader = response.body?.getReader();
  if (!reader) {
    if (typeof response.arrayBuffer !== 'function') {
      // Some test/native response shims expose only the standard JSON reader.
      // Real fetch Response objects take one of the byte-counted paths below.
      return response.json() as Promise<unknown>;
    }
    // Older native fetch implementations do not expose a ReadableStream. The
    // post-read byte check remains fail-closed, while modern Android/iOS builds
    // take the streamed path and stop reading as soon as the cap is exceeded.
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > maximumBytes) throw new ResponseBodyTooLargeError();
    return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
  }

  const decoder = new TextDecoder();
  let bytesRead = 0;
  let text = '';
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      if (!next.value?.byteLength) continue;
      bytesRead += next.value.byteLength;
      if (bytesRead > maximumBytes) {
        await reader.cancel('Response exceeded its allowed size.').catch(() => undefined);
        throw new ResponseBodyTooLargeError();
      }
      text += decoder.decode(next.value, { stream: true });
    }
    text += decoder.decode();
    return JSON.parse(text) as unknown;
  } finally {
    reader.releaseLock();
  }
}

async function apiError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get('content-type') ?? '';
  let message = 'The server could not complete this request.';
  let code = `HTTP_${response.status}`;

  if (contentType.includes('application/json')) {
    try {
      const result = ApiErrorBodySchema.safeParse(
        await readJsonBodyBounded(response, MAX_ERROR_JSON_BYTES),
      );
      if (result.success) {
        if ('error' in result.data) {
          message = result.data.error.message;
          code = result.data.error.code;
        } else if (typeof result.data.detail === 'string') {
          message = result.data.detail;
        } else {
          message = result.data.detail.message;
          code = result.data.detail.code;
        }
      }
    } catch {
      // Keep the generic error. Response bodies are untrusted and intentionally not logged.
    }
  }

  return new ApiError(
    message,
    response.status,
    code,
    parseRetryAfter(response.headers.get('retry-after')),
  );
}

async function apiRequestInternal<T>(
  path: string,
  options: ApiRequestOptions<T>,
): Promise<T> {
  if (isDemoMode()) {
    throw new ApiError(
      'This emulator demo uses local sample data and cannot contact the server.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const authenticated = options.authenticated ?? true;
  const authentication = authenticated ? captureAuthenticationSnapshot() : null;
  const timeout = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const token = authentication?.accessToken ?? null;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Cache-Control': 'no-store',
    'X-Request-ID': Crypto.randomUUID(),
    ...options.headers,
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(endpointUrl(path), {
    method: options.method ?? 'GET',
    headers,
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    credentials: 'omit',
    redirect: 'error',
    signal,
  });

  assertAuthenticationContextCurrent(authentication);

  if (response.status === 401 && authentication && (options.retryAuthentication ?? true)) {
    const latestToken = currentAccessToken();
    const refreshedToken = latestToken !== authentication.accessToken
      ? latestToken
      : await refreshAccessToken(authentication);
    assertAuthenticationContextCurrent(authentication);
    if (refreshedToken) {
      return apiRequestInternal(path, { ...options, retryAuthentication: false });
    }
  }

  if (!response.ok) {
    await handleAccessDenied(path, response.status);
    assertAuthenticationContextCurrent(authentication);
    const error = await apiError(response);
    assertAuthenticationContextCurrent(authentication);
    throw error;
  }

  if (response.status === 204) {
    const result = options.schema.safeParse(null);
    if (!result.success) {
      throw new ApiError('The server returned an empty response for a non-empty contract.', 502, 'INVALID_RESPONSE', null);
    }
    assertAuthenticationContextCurrent(authentication);
    return result.data;
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new ApiError('The server returned an invalid response type.', 502, 'INVALID_CONTENT_TYPE', null);
  }

  let value: unknown;
  try {
    value = await readJsonBodyBounded(response, MAX_JSON_BYTES);
  } catch (error) {
    assertAuthenticationContextCurrent(authentication);
    if (error instanceof ResponseBodyTooLargeError) {
      throw new ApiError('The server returned an unexpectedly large response.', 502, 'PAYLOAD_TOO_LARGE', null);
    }
    throw new ApiError('The server returned malformed JSON.', 502, 'INVALID_RESPONSE', null);
  }
  const result = options.schema.safeParse(value);
  if (!result.success) {
    throw new ApiError('The server response did not match the mobile contract.', 502, 'INVALID_RESPONSE', null);
  }
  assertAuthenticationContextCurrent(authentication);
  return result.data;
}

function apiFailureOutcome(
  error: unknown,
  callerSignal?: AbortSignal,
): ApiMetricOutcome {
  if (callerSignal?.aborted) return 'cancelled';
  if (
    typeof error === 'object'
    && error !== null
    && 'name' in error
    && error.name === 'TimeoutError'
  ) return 'timeout';
  return 'failure';
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions<T>,
): Promise<T> {
  const startedAtMs = performance.now();
  let outcome: ApiMetricOutcome = 'failure';
  try {
    const result = await apiRequestInternal(path, options);
    outcome = 'success';
    return result;
  } catch (error) {
    outcome = apiFailureOutcome(error, options.signal);
    throw error;
  } finally {
    recordMobileMetric('api_request_duration', performance.now() - startedAtMs, { outcome });
  }
}

/**
 * Fetches an authenticated file directly into one app-private native path.
 * This preserves normal access-token rotation without allocating the complete
 * response in Hermes.
 */
export async function apiDownloadToFile(
  path: string,
  options: ApiFileDownloadOptions,
): Promise<NativeFileDownloadResult> {
  if (isDemoMode()) {
    throw new ApiError(
      'This emulator demo uses local sample data and cannot contact the server.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const authentication = captureAuthenticationSnapshot();
  const token = authentication.accessToken;
  if (!token) throw new ApiError('Authentication is required.', 401, 'AUTH_REQUIRED', null);
  const response = await nativeFileRequest({
    authentication,
    destinationPath: options.destinationPath,
    headers: {
      Accept: options.accept,
      Authorization: `Bearer ${token}`,
      'Cache-Control': 'no-store',
      'X-Request-ID': Crypto.randomUUID(),
    },
    maximumBytes: options.maximumBytes,
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    url: endpointUrl(path),
    ...(options.signal ? { signal: options.signal } : {}),
  });
  if (response.status === 401 && (options.retryAuthentication ?? true)) {
    const latestToken = currentAccessToken();
    const refreshedToken = latestToken !== authentication.accessToken
      ? latestToken
      : await refreshAccessToken(authentication);
    assertAuthenticationContextCurrent(authentication);
    if (refreshedToken) {
      return apiDownloadToFile(path, { ...options, retryAuthentication: false });
    }
  }
  if (response.status < 200 || response.status >= 300) {
    await handleAccessDenied(path, response.status);
    assertAuthenticationContextCurrent(authentication);
    throw new ApiError(
      'The server could not complete this file request.',
      response.status,
      `HTTP_${response.status}`,
      null,
    );
  }
  assertAuthenticationContextCurrent(authentication);
  return response;
}

export async function authorizedDownloadToFile(
  path: string,
  downloadToken: string,
  destinationPath: string,
  maximumBytes: number,
  signal?: AbortSignal,
  rangeStart = 0,
): Promise<NativeFileDownloadResult> {
  if (isDemoMode()) {
    throw new ApiError(
      'Document downloads are disabled in the local emulator demo.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const authentication = captureAuthenticationSnapshot();
  const token = authentication.accessToken;
  if (!token) throw new ApiError('Authentication is required.', 401, 'AUTH_REQUIRED', null);
  if (!/^[A-Za-z0-9._~-]{32,4096}$/.test(downloadToken)) {
    throw new ApiError('The download authorization was invalid.', 400, 'INVALID_DOWNLOAD_TOKEN', null);
  }
  if (!Number.isSafeInteger(rangeStart) || rangeStart < 0) {
    throw new ApiError('The download range was invalid.', 400, 'INVALID_DOWNLOAD_RANGE', null);
  }
  const headers: Record<string, string> = {
    Accept: 'application/pdf,image/jpeg,image/png,image/webp',
    Authorization: `Bearer ${token}`,
    'Cache-Control': 'no-store',
    'X-GC-Download-Token': downloadToken,
    'X-Request-ID': Crypto.randomUUID(),
  };
  if (rangeStart > 0) headers.Range = `bytes=${rangeStart}-`;
  const response = await nativeFileRequest({
    authentication,
    destinationPath,
    headers,
    maximumBytes,
    timeoutMs: 60_000,
    url: authorizedDocumentUrl(path),
    ...(signal ? { signal } : {}),
  });
  if (response.status === 401) {
    throw new ApiError(
      'The document authorization expired and will be refreshed.',
      401,
      'DOWNLOAD_AUTH_EXPIRED',
      null,
    );
  }
  if (response.status < 200 || response.status >= 300) {
    await handleAccessDenied(path, response.status);
    assertAuthenticationContextCurrent(authentication);
    throw new ApiError(
      'The server could not complete this document download.',
      response.status,
      `HTTP_${response.status}`,
      null,
    );
  }
  assertAuthenticationContextCurrent(authentication);
  return response;
}
