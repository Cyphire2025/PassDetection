"use client";

import { selectUser, useAuthStore } from "@/stores/auth.store";

/** One cache identity for company data; authority changes always create a new key. */
export function useCompanySession() {
  const user = useAuthStore(selectUser);
  const version = useAuthStore((state) => state.sessionVersion);
  const changing = useAuthStore((state) => state.isChangingAccessLevel);
  return {
    key: JSON.stringify([user?.id, user?.role, user?.agency_id, version]),
    ready: Boolean(user) && !changing,
  };
}
