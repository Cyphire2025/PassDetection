/**
 * API Client
 * ==========
 * Uses same-origin requests with httpOnly auth cookies. On a 401 it performs
 * one cookie-based refresh, then retries the original request.
 */

import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";
import {
  readRefreshEpoch,
  runCoordinatedRefresh,
} from "@/features/auth/services/refresh-coordinator";
import { requestAuthenticationStepUp } from "@/features/auth/services/step-up-coordinator";
import { useAuthStore } from "@/stores/auth.store";
import type { AuthSession } from "@/types";
import {
  parseRetryAfterMs,
  retryAfterHeaderValue,
} from "./retry-after";
import { resolveServerApiBaseUrl } from "@/config/api-routing";
import { normalizeStructuredApiErrorDetail } from "./api-error-detail";

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
  status?: number;
  retryAfterMs?: number;
}

export interface ApiErrorResponse {
  error?: ApiError;
  detail?: string | {
    code?: unknown;
    message?: unknown;
    [key: string]: unknown;
  };
}

interface RetriableRequestConfig extends InternalAxiosRequestConfig {
  _authRetry?: boolean;
  _authEpoch?: string;
  _stepUpRetry?: boolean;
}

const SESSION_EXPIRED_ERROR: ApiError = {
  code: "AUTH_SESSION_EXPIRED",
  message: "Your session expired. Please sign in again.",
};

let refreshPromise: Promise<AuthSession | null> | null = null;
let expirationPromise: Promise<void> | null = null;

const apiBaseUrl = typeof window === "undefined"
  ? resolveServerApiBaseUrl({
      NODE_ENV: process.env.NODE_ENV,
      API_BASE_URL: process.env.API_BASE_URL,
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    })
  : "";

const apiClient: AxiosInstance = axios.create({
  baseURL: apiBaseUrl,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

apiClient.interceptors.request.use((config) => {
  (config as RetriableRequestConfig)._authEpoch = readRefreshEpoch();
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorResponse>) => {
    const originalRequest = error.config as RetriableRequestConfig | undefined;
    const responseData = await decodeApiErrorResponse(error.response?.data);
    const shouldStepUp =
      error.response?.status === 403 &&
      responseData?.error?.code === "STEP_UP_REQUIRED" &&
      originalRequest !== undefined &&
      originalRequest._stepUpRetry !== true &&
      isStepUpEligibleRequest(originalRequest.url);

    if (shouldStepUp) {
      originalRequest._stepUpRetry = true;
      await requestAuthenticationStepUp();
      return apiClient(originalRequest);
    }
    const shouldRefresh =
      error.response?.status === 401 &&
      originalRequest !== undefined &&
      originalRequest._authRetry !== true &&
      isRefreshEligibleRequest(originalRequest.url);

    if (shouldRefresh) {
      // Mark every failed request before it waits on the shared refresh. A
      // retried request can therefore never start another refresh cycle.
      originalRequest._authRetry = true;

      await getRefreshPromise(originalRequest._authEpoch ?? readRefreshEpoch());
      return apiClient(originalRequest);
    }

    return Promise.reject(await buildApiError(error));
  },
);

async function buildApiError(error: AxiosError<ApiErrorResponse>): Promise<ApiError> {
  const responseData = await decodeApiErrorResponse(error.response?.data);
  const structuredError = responseData?.error;
  const responseStatus = error.response?.status;
  const retryAfterMs = responseStatus === 429 || responseStatus === 503
    ? parseRetryAfterMs(retryAfterHeaderValue(error.response?.headers))
    : undefined;
  if (structuredError) {
    return {
      ...structuredError,
      ...(responseStatus === undefined ? {} : { status: responseStatus }),
      ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
    };
  }
  const detail = responseData?.detail;
  const structuredDetail = normalizeStructuredApiErrorDetail(detail);
  if (structuredDetail) {
    return {
      ...structuredDetail,
      ...(responseStatus === undefined ? {} : { status: responseStatus }),
      ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
    };
  }
  if (typeof detail === "string" && detail) {
    return {
      code: `HTTP_${responseStatus ?? "ERROR"}`,
      message: detail,
      ...(responseStatus === undefined ? {} : { status: responseStatus }),
      ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
    };
  }
  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return {
      code: "REQUEST_TIMEOUT",
      message: "The server took too long to respond. Please try again.",
    };
  }
  if (!error.response) {
    return {
      code: "NETWORK_ERROR",
      message: "Unable to reach the server. Check your connection and try again.",
    };
  }
  return {
    code: `HTTP_${responseStatus}`,
    message: "The request could not be completed. Please try again.",
    ...(responseStatus === undefined ? {} : { status: responseStatus }),
    ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
  };
}

async function decodeApiErrorResponse(
  responseData: ApiErrorResponse | Blob | undefined,
): Promise<ApiErrorResponse | undefined> {
  if (typeof Blob !== "undefined" && responseData instanceof Blob) {
    try {
      const parsed: unknown = JSON.parse(await responseData.text());
      if (typeof parsed !== "object" || parsed === null) return undefined;
      return parsed as ApiErrorResponse;
    } catch {
      return undefined;
    }
  }
  return responseData as ApiErrorResponse | undefined;
}

function getRefreshPromise(observedEpoch: string) {
  if (refreshPromise) return refreshPromise;

  let refreshedSession: AuthSession | null = null;
  refreshPromise = runCoordinatedRefresh(
    observedEpoch,
    async () => {
      const response = await axios.post<AuthSession>(
        `${apiBaseUrl}/api/v1/auth/refresh`,
        undefined,
        {
          withCredentials: true,
          timeout: 10_000,
          headers: { "Content-Type": "application/json" },
        },
      );
      refreshedSession = response.data;
    },
  )
    .then(() => refreshedSession)
    .catch(async (error: unknown) => {
      if (
        axios.isAxiosError(error) &&
        (error.response?.status === 401 || error.response?.status === 403)
      ) {
        await expireSession();
        throw SESSION_EXPIRED_ERROR;
      }
      if (axios.isAxiosError<ApiErrorResponse>(error)) {
        throw await buildApiError(error);
      }
      throw error;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

export function refreshAuthenticatedSession() {
  return getRefreshPromise(readRefreshEpoch());
}

function expireSession() {
  if (expirationPromise) return expirationPromise;

  const expiring = (async () => {
    if (typeof window === "undefined") return;

    await useAuthStore.getState().clearSession("session_expired", {
      // A rejected refresh already proves that the server session cannot be
      // reused. Avoid delaying navigation on a redundant logout request.
      revokeServerSession: false,
    });
  })().finally(() => {
    if (expirationPromise === expiring) expirationPromise = null;
  });

  expirationPromise = expiring;
  return expirationPromise;
}

function isRefreshEligibleRequest(url: string | undefined) {
  if (!url) return false;

  // Authentication commands and public traveller flows have their own 401
  // semantics. A revoked public link must never redirect a traveller to the
  // staff login page or attempt to use an unrelated staff refresh cookie.
  if (/\/api\/v1\/auth\/(?:login|refresh|logout|logout-all)(?:[/?]|$)/.test(url)) {
    return false;
  }
  if (url.includes("/api/v1/passports/upload/")) return false;
  if (url.includes("/api/v1/upload-links/token/")) return false;
  if (/\/api\/v1\/passports\/[^/]+\/client-submit(?:[/?]|$)/.test(url)) return false;

  return true;
}

function isStepUpEligibleRequest(url: string | undefined) {
  if (!url) return false;
  return !/\/api\/v1\/auth\/(?:login|refresh|mfa\/verify|mfa\/step-up)(?:[/?]|$)/.test(url);
}

export default apiClient;
