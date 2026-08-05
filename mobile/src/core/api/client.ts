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

import { ApiErrorBodySchema } from './contracts';

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_JSON_BYTES = 2 * 1024 * 1024;
const MAX_ERROR_JSON_BYTES = 64 * 1024;

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

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly retryAfterSeconds: number | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

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

export type ApiResponseOptions = {
  accept: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  retryAuthentication?: boolean;
};

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

function endpointUrl(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new Error('API paths must be root-relative.');
  }
  return `${env.apiUrl}${path}`;
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
        if (typeof result.data.detail === 'string') message = result.data.detail;
        else {
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

export async function apiRequest<T>(
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
  const token = authenticated ? currentAccessToken() : null;

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

  if (authentication && !isAuthenticationEpochCurrent(authentication.epoch)) {
    throw authenticationContextChanged();
  }

  if (response.status === 401 && authentication && (options.retryAuthentication ?? true)) {
    const latestToken = currentAccessToken();
    if (
      latestToken !== authentication.accessToken ||
      (await refreshAccessToken(authentication))
    ) {
      if (!isAuthenticationEpochCurrent(authentication.epoch)) {
        throw authenticationContextChanged();
      }
      return apiRequest(path, { ...options, retryAuthentication: false });
    }
    if (!isAuthenticationEpochCurrent(authentication.epoch)) {
      throw authenticationContextChanged();
    }
  }

  if (!response.ok) {
    await handleAccessDenied(path, response.status);
    throw await apiError(response);
  }

  if (response.status === 204) {
    const result = options.schema.safeParse(null);
    if (!result.success) {
      throw new ApiError('The server returned an empty response for a non-empty contract.', 502, 'INVALID_RESPONSE', null);
    }
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
    if (error instanceof ResponseBodyTooLargeError) {
      throw new ApiError('The server returned an unexpectedly large response.', 502, 'PAYLOAD_TOO_LARGE', null);
    }
    throw new ApiError('The server returned malformed JSON.', 502, 'INVALID_RESPONSE', null);
  }
  const result = options.schema.safeParse(value);
  if (!result.success) {
    throw new ApiError('The server response did not match the mobile contract.', 502, 'INVALID_RESPONSE', null);
  }
  return result.data;
}

/** Fetch an authenticated, same-origin non-JSON response with normal token refresh. */
export async function apiResponse(
  path: string,
  options: ApiResponseOptions,
): Promise<Response> {
  if (isDemoMode()) {
    throw new ApiError(
      'This emulator demo uses local sample data and cannot contact the server.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const authentication = captureAuthenticationSnapshot();
  const token = currentAccessToken();
  if (!token) throw new ApiError('Authentication is required.', 401, 'AUTH_REQUIRED', null);
  const timeout = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const response = await fetch(endpointUrl(path), {
    method: 'GET',
    headers: {
      Accept: options.accept,
      Authorization: `Bearer ${token}`,
      'Cache-Control': 'no-store',
      'X-Request-ID': Crypto.randomUUID(),
    },
    credentials: 'omit',
    redirect: 'error',
    signal,
  });

  if (!isAuthenticationEpochCurrent(authentication.epoch)) {
    throw authenticationContextChanged();
  }
  if (response.status === 401 && (options.retryAuthentication ?? true)) {
    const latestToken = currentAccessToken();
    if (
      latestToken !== authentication.accessToken
      || (await refreshAccessToken(authentication))
    ) {
      if (!isAuthenticationEpochCurrent(authentication.epoch)) {
        throw authenticationContextChanged();
      }
      return apiResponse(path, { ...options, retryAuthentication: false });
    }
  }
  if (!response.ok) {
    await handleAccessDenied(path, response.status);
    throw await apiError(response);
  }
  return response;
}

export async function authorizedDownloadResponse(
  path: string,
  downloadToken: string,
  signal?: AbortSignal,
  rangeStart = 0,
): Promise<Response> {
  if (isDemoMode()) {
    throw new ApiError(
      'Document downloads are disabled in the local emulator demo.',
      503,
      'DEMO_LOCAL_ONLY',
      null,
    );
  }
  const token = currentAccessToken();
  if (!token) throw new ApiError('Authentication is required.', 401, 'AUTH_REQUIRED', null);
  const authentication = captureAuthenticationSnapshot();
  if (!/^[A-Za-z0-9._~-]{32,4096}$/.test(downloadToken)) {
    throw new ApiError('The download authorization was invalid.', 400, 'INVALID_DOWNLOAD_TOKEN', null);
  }
  if (!Number.isSafeInteger(rangeStart) || rangeStart < 0) {
    throw new ApiError('The download range was invalid.', 400, 'INVALID_DOWNLOAD_RANGE', null);
  }

  const apiBase = new URL(env.apiUrl);
  const parsedPath = new URL(path, apiBase.origin);
  const basePath = apiBase.pathname.replace(/\/$/, '');
  if (
    !path.startsWith('/') ||
    path.startsWith('//') ||
    parsedPath.origin !== apiBase.origin ||
    (!parsedPath.pathname.startsWith(`${basePath}/mobile/`) &&
      !parsedPath.pathname.startsWith('/mobile/'))
  ) {
    throw new ApiError('The download path was invalid.', 400, 'INVALID_DOWNLOAD_PATH', null);
  }
  const downloadUrl = parsedPath.pathname.startsWith(`${basePath}/mobile/`)
    ? `${apiBase.origin}${parsedPath.pathname}${parsedPath.search}`
    : `${env.apiUrl}${parsedPath.pathname}${parsedPath.search}`;

  const timeout = AbortSignal.timeout(60_000);
  const combinedSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const headers: Record<string, string> = {
    Accept: 'application/pdf,image/jpeg,image/png,image/webp',
    Authorization: `Bearer ${token}`,
    'Cache-Control': 'no-store',
    'X-GC-Download-Token': downloadToken,
    'X-Request-ID': Crypto.randomUUID(),
  };
  if (rangeStart > 0) headers.Range = `bytes=${rangeStart}-`;
  const response = await fetch(downloadUrl, {
    method: 'GET',
    headers,
    credentials: 'omit',
    redirect: 'error',
    signal: combinedSignal,
  });
  if (!isAuthenticationEpochCurrent(authentication.epoch)) {
    throw authenticationContextChanged();
  }
  if (!response.ok) {
    if (response.status === 401) {
      const expired = await apiError(response);
      // A short-lived document grant can expire independently of the device
      // session during a slow/resumed transfer. Let the document manager obtain
      // a fresh grant; that endpoint still re-checks tenant, trip, passenger and
      // access generation before another byte can be downloaded.
      throw new ApiError(
        'The document authorization expired and will be refreshed.',
        401,
        'DOWNLOAD_AUTH_EXPIRED',
        expired.retryAfterSeconds,
      );
    }
    await handleAccessDenied(path, response.status);
    throw await apiError(response);
  }
  return response;
}
