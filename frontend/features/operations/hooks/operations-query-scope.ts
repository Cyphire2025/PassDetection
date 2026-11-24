import { useAuthStore } from "@/stores/auth.store";

export const MANAGED_ACCOUNTS_QUERY_KEY = ["operations", "managed-accounts"] as const;

export const STAFF_ACCOUNTS_QUERY_KEY = ["operations", "staff-accounts"] as const;

export const STAFF_ACCESS_QUERY_KEY = ["operations", "staff-access"] as const;

export const roomingWorkspaceKey = (groupId: string) => ["operations", "rooming", groupId] as const;

export function useAuthenticatedQueryScope(): string {
  return useAuthStore((state) => [
    state.sessionVersion,
    state.user?.id ?? "anonymous",
    state.user?.agency_id ?? "global",
    state.user?.role ?? "none",
  ].join(":"));
}
