import * as Crypto from 'expo-crypto';
import type { ZodType } from 'zod';

import { currentAccessToken } from '@/core/auth/session-store';
import { env } from '@/core/config/env';
import { isDemoMode } from '@/core/demo/demo-mode';

import { ApiErrorBodySchema } from './contracts';

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_JSON_BYTES = 2 * 1024 * 1024;

type RefreshHandler = () => Promise<string | null>;
type AccessDeniedHandler = (path: string, status: number) => Promise<void>;
let refreshHandler: RefreshHandler | null = null;
let accessDeniedHandler: AccessDeniedHandler | null = null;
let refreshInFlight: Promise<string | null> | null = null;

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

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshHandler) return null;
  if (!refreshInFlight) {
    refreshInFlight = refreshHandler().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value || !/^\d{1,6}$/.test(value)) return null;
  return Number(value);
}

async function apiError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get('content-type') ?? '';
  let message = 'The server could not complete this request.';
  let code = `HTTP_${response.status}`;

  if (contentType.includes('application/json')) {
    try {
      const result = ApiErrorBodySchema.safeParse(await response.json());
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

  if (
    response.status === 401 &&
    authenticated &&
    (options.retryAuthentication ?? true) &&
    (await refreshAccessToken())
  ) {
    return apiRequest(path, { ...options, retryAuthentication: false });
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

  const length = response.headers.get('content-length');
  if (length && /^\d+$/.test(length) && Number(length) > MAX_JSON_BYTES) {
    throw new ApiError('The server returned an unexpectedly large response.', 502, 'PAYLOAD_TOO_LARGE', null);
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new ApiError('The server returned an invalid response type.', 502, 'INVALID_CONTENT_TYPE', null);
  }

  const value: unknown = await response.json();
  const result = options.schema.safeParse(value);
  if (!result.success) {
    throw new ApiError('The server response did not match the mobile contract.', 502, 'INVALID_RESPONSE', null);
  }
  return result.data;
}

export async function authorizedDownloadResponse(
  path: string,
  downloadToken: string,
  signal?: AbortSignal,
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
  if (!/^[A-Za-z0-9._~-]{32,4096}$/.test(downloadToken)) {
    throw new ApiError('The download authorization was invalid.', 400, 'INVALID_DOWNLOAD_TOKEN', null);
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
  const response = await fetch(downloadUrl, {
    method: 'GET',
    headers: {
      Accept: 'application/pdf,image/jpeg,image/png,image/webp,application/octet-stream',
      Authorization: `Bearer ${token}`,
      'Cache-Control': 'no-store',
      'X-GC-Download-Token': downloadToken,
      'X-Request-ID': Crypto.randomUUID(),
    },
    credentials: 'omit',
    redirect: 'error',
    signal: combinedSignal,
  });
  if (!response.ok) {
    await handleAccessDenied(path, response.status);
    throw await apiError(response);
  }
  return response;
}
