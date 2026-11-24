import axios, { CanceledError, type AxiosAdapter, type AxiosRequestConfig, type InternalAxiosRequestConfig } from "axios";

const COOKIE_WRITER_LOCK = "passdetection-auth-cookie-writer";
const activeTransports = new WeakSet<InternalAxiosRequestConfig>();
const COOKIE_WRITER_PATH = /^\/api\/v1\/auth\/(?:login|refresh|logout(?:-all)?|activate|access-level|mfa\/(?:verify|step-up)|password\/(?:change|recovery\/complete))$/;

export class CookieCoordinationUnavailableError extends Error {
  readonly code = "AUTH_COOKIE_COORDINATION_UNAVAILABLE";

  constructor() {
    super("Secure sign-in is unavailable in this browser. Use HTTPS or localhost in a supported browser, then retry.");
    this.name = "CookieCoordinationUnavailableError";
  }
}

export function cookieCoordinationFailureMessage(error: unknown): string | undefined {
  return (error as { code?: unknown } | null)?.code === "AUTH_COOKIE_COORDINATION_UNAVAILABLE"
    ? new CookieCoordinationUnavailableError().message : undefined;
}

/** Lock only the HTTP transport; auth recovery must run after it releases. */
export async function coordinateCookieMutation<T>(
  operation: () => Promise<T>, signal?: AxiosRequestConfig["signal"],
): Promise<T> {
  if (typeof window === "undefined") return operation();
  if (!navigator.locks?.request) throw new CookieCoordinationUnavailableError();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener?.("abort", cancel);
  if (signal?.aborted) controller.abort();
  try {
    return await navigator.locks.request(COOKIE_WRITER_LOCK, {
      mode: "exclusive", signal: controller.signal,
    }, () => {
      if (signal?.aborted) throw new CanceledError();
      return operation();
    });
  } finally {
    signal?.removeEventListener?.("abort", cancel);
  }
}

export function cookieMutationAdapter(delegate: AxiosAdapter): AxiosAdapter {
  return async (config) => {
    const path = config.url?.split(/[?#]/, 1)[0] ?? "";
    if (config.method?.toLowerCase() !== "post" || !COOKIE_WRITER_PATH.test(path)
      || activeTransports.has(config)) return delegate(config);
    return coordinateCookieMutation(async () => {
      // Retried Axios configs may retain a previously wrapped adapter. A single
      // dispatch shares the outer lock; subsequent retries acquire it afresh.
      activeTransports.add(config);
      try { return await delegate(config); }
      finally { activeTransports.delete(config); }
    }, config.signal);
  };
}

/** Raw refresh uses the same transport boundary without apiClient interceptors. */
export function coordinatedCookieAdapter(): AxiosAdapter {
  return cookieMutationAdapter(axios.getAdapter(axios.defaults.adapter));
}
