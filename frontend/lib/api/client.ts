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
import { useAuthStore } from "@/stores/auth.store";

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiErrorResponse {
  error?: ApiError;
  detail?: string;
}

interface RetriableRequestConfig extends InternalAxiosRequestConfig {
  _authRetry?: boolean;
  _authEpoch?: string;
}

const SESSION_EXPIRED_ERROR: ApiError = {
  code: "AUTH_SESSION_EXPIRED",
  message: "Your session expired. Please sign in again.",
};

let refreshPromise: Promise<void> | null = null;
let expirationPromise: Promise<void> | null = null;

const apiBaseUrl = typeof window === "undefined"
  ? (process.env.NEXT_PUBLIC_API_BASE_URL ?? "")
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
  if (structuredError) return structuredError;
  const detail = responseData?.detail;
  if (detail) {
    return {
      code: `HTTP_${error.response?.status ?? "ERROR"}`,
      message: detail,
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
    code: `HTTP_${error.response.status}`,
    message: "The request could not be completed. Please try again.",
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

  refreshPromise = runCoordinatedRefresh(
    observedEpoch,
    async () => {
      await axios.post(`${apiBaseUrl}/api/v1/auth/refresh`, undefined, {
        withCredentials: true,
        timeout: 10_000,
        headers: { "Content-Type": "application/json" },
      });
    },
  )
    .catch(async () => {
      await expireSession();
      throw SESSION_EXPIRED_ERROR;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

function expireSession() {
  if (expirationPromise) return expirationPromise;

  const expiring = (async () => {
    if (typeof window === "undefined") return;

    await useAuthStore.getState().clearSession("session_expired");
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

export default apiClient;
