/**
 * API Client
 * ==========
 * Uses same-origin requests with httpOnly auth cookies. On a 401 it performs
 * one cookie-based refresh, then retries the original request.
 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from "axios";

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiErrorResponse {
  error: ApiError;
}

let isRefreshing = false;
let failedQueue: Array<{
  resolve: () => void;
  reject: (reason: ApiError) => void;
}> = [];

function processQueue(error: ApiError | null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve();
  });
  failedQueue = [];
}

function clearAuthAndRedirect() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("passdetection:auth-expired"));
  if (!window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
}

const apiBaseUrl = typeof window === "undefined"
  ? (process.env.NEXT_PUBLIC_API_BASE_URL ?? "")
  : "";

const apiClient: AxiosInstance = axios.create({
  baseURL: apiBaseUrl,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorResponse>) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise<void>((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(() => apiClient(originalRequest));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        await axios.post(`${apiBaseUrl}/api/v1/auth/refresh`, undefined, { withCredentials: true });
        processQueue(null);
        return apiClient(originalRequest);
      } catch {
        const apiError = buildApiError(error);
        processQueue(apiError);
        clearAuthAndRedirect();
        return Promise.reject(apiError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(buildApiError(error));
  },
);

function buildApiError(error: AxiosError<ApiErrorResponse>): ApiError {
  return (
    error.response?.data?.error ?? {
      code: "NETWORK_ERROR",
      message: error.message ?? "An unexpected error occurred",
    }
  );
}

export default apiClient;
