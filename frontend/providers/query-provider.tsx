/**
 * TanStack Query Provider
 *
 * Wraps the application with QueryClientProvider.
 * Configured with sensible enterprise defaults:
 *   - Stale time: 5 minutes (data considered fresh)
 *   - Retry: 2 times with exponential backoff
 *   - Stale active data recovers after focus, reconnect, and sleep/wake
 */

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";
import { SessionLifecycle } from "./session-lifecycle";

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,   // 5 minutes
            gcTime: 10 * 60 * 1000,      // 10 minutes garbage collection
            retry: (failureCount, error) => shouldRetryQuery(failureCount, error),
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30_000),
            refetchOnWindowFocus: true,
            refetchOnReconnect: "always",
          },
          mutations: {
            retry: 0,                    // Never retry mutations automatically
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <SessionLifecycle queryClient={queryClient} />
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}

export function shouldRetryQuery(failureCount: number, error: unknown) {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? String(error.code)
      : "";
  const status =
    typeof error === "object" && error !== null && "status" in error
      ? Number(error.status)
      : null;

  if (
    (status !== null && Number.isInteger(status) && status >= 400 && status < 500)
    || code.startsWith("AUTH_")
    || /^HTTP_4\d\d$/.test(code)
    || code.includes("RATE_LIMITED")
  ) return false;
  return failureCount < 2;
}
