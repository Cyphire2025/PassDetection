/**
 * API Client — Updated for Phase 2
 * ==================================
 * Adds transparent token refresh:
 *   - On 401, attempt one token refresh via /api/v1/auth/refresh
 *   - If refresh succeeds, retry the original request
 *   - If refresh fails, clear session and redirect to login
 *
 * Uses a queue to handle concurrent 401s gracefully —
 * only one refresh request fires; others wait for it.
 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from "axios";

// ── Types ──────────────────────────────────────────────────────────────────

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiErrorResponse {
  error: ApiError;
}

// ── Refresh queue (prevents multiple concurrent refresh calls) ─────────────

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: string) => void;
  reject: (reason: ApiError) => void;
}> = [];

function processQueue(error: ApiError | null, token: string | null = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token!);
  });
  failedQueue = [];
}

// ── Helper to read tokens from storage ────────────────────────────────────

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const auth = localStorage.getItem("passdetection-auth");
    if (!auth) return null;
    const parsed = JSON.parse(auth) as { state?: { tokens?: { access_token?: string } } };
    return parsed?.state?.tokens?.access_token ?? null;
  } catch {
    return null;
  }
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const auth = localStorage.getItem("passdetection-auth");
    if (!auth) return null;
    const parsed = JSON.parse(auth) as { state?: { tokens?: { refresh_token?: string } } };
    return parsed?.state?.tokens?.refresh_token ?? null;
  } catch {
    return null;
  }
}

function clearAuthAndRedirect() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("passdetection-auth");
  window.location.href = "/login";
}

// ── Axios Instance ─────────────────────────────────────────────────────────

// Browser requests must remain same-origin so LAN clients call Nginx on the
// computer hosting the app, never `localhost` on the phone/tablet itself.
const apiBaseUrl = typeof window === "undefined"
  ? (process.env.NEXT_PUBLIC_API_BASE_URL ?? "")
  : "";

const apiClient: AxiosInstance = axios.create({
  baseURL: apiBaseUrl,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

// ── Request Interceptor — Inject Access Token ──────────────────────────────

apiClient.interceptors.request.use(
  (config) => {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response Interceptor — Handle 401 with Refresh ────────────────────────

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorResponse>) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean };

    // Only attempt refresh on 401 and only once per request
    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = getRefreshToken();

      if (!refreshToken) {
        clearAuthAndRedirect();
        return Promise.reject(buildApiError(error));
      }

      if (isRefreshing) {
        // Queue this request until the ongoing refresh completes
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers = {
            ...originalRequest.headers,
            Authorization: `Bearer ${token}`,
          };
          return apiClient(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const { data } = await axios.post(
          `${apiBaseUrl}/api/v1/auth/refresh`,
          { refresh_token: refreshToken }
        );

        // Update stored tokens
        const auth = localStorage.getItem("passdetection-auth");
        if (auth) {
          const parsed = JSON.parse(auth);
          if (parsed?.state?.tokens) {
            parsed.state.tokens.access_token  = data.access_token;
            parsed.state.tokens.refresh_token = data.refresh_token;
            localStorage.setItem("passdetection-auth", JSON.stringify(parsed));
          }
        }

        processQueue(null, data.access_token);
        originalRequest.headers = {
          ...originalRequest.headers,
          Authorization: `Bearer ${data.access_token}`,
        };
        return apiClient(originalRequest);
      } catch {
        processQueue(buildApiError(error), null);
        clearAuthAndRedirect();
        return Promise.reject(buildApiError(error));
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(buildApiError(error));
  }
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
