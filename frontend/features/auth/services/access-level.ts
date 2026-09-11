import type { QueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth.store";
import type { AccessLevelAgencyChoice, SwitchableAccessLevel } from "@/types";
import { authApi } from "../api/auth.api";
import { navigateToAccessLevel } from "./access-level-navigation";
import { clearSensitiveBrowserState } from "./session-state";

function errorMessage(error: unknown): string {
  const message = (error as { message?: unknown } | null)?.message;
  return typeof message === "string" ? message : "Could not change access level. Please try again.";
}

function agencyChoices(error: unknown, role: SwitchableAccessLevel): AccessLevelAgencyChoice | null {
  const detail = error as { code?: string; details?: { agencies?: unknown } } | null;
  if (detail?.code !== "ACCESS_LEVEL_AGENCY_REQUIRED" || !Array.isArray(detail.details?.agencies)) return null;
  const agencies = detail.details.agencies.filter((agency): agency is { id: string; name: string } => (
    typeof agency?.id === "string" && typeof agency?.name === "string"
  ));
  return { role, agencies };
}

export async function changeAccessLevel(role: SwitchableAccessLevel, queryClient: QueryClient, agencyId?: string) {
  const state = useAuthStore.getState();
  if (state.isChangingAccessLevel || !state.user?.can_switch_access_level
      || state.user.actual_role !== "super_admin" || (state.user.role === role && !agencyId)) return;

  state.beginAccessLevelChange();
  const expectedVersion = useAuthStore.getState().sessionVersion;
  const isCurrent = () => useAuthStore.getState().sessionVersion === expectedVersion;
  await queryClient.cancelQueries();
  queryClient.clear();

  let mutationError: unknown;
  try {
    await (agencyId ? authApi.changeAccessLevel(role, agencyId) : authApi.changeAccessLevel(role));
  } catch (error) {
    mutationError = error;
  }
  if (!isCurrent()) return;

  // Cookies are shared between tabs. Reset their role-scoped data as well;
  // owner-scoped unsent attendance scans remain preserved by this cleanup.
  await clearSensitiveBrowserState("access_level_changed");
  try {
    const confirmedUser = await authApi.getMe();
    if (!isCurrent()) return;
    if (confirmedUser.role !== role) {
      useAuthStore.getState().failAccessLevelChange(errorMessage(mutationError), confirmedUser);
      const choices = agencyChoices(mutationError, role);
      if (choices) useAuthStore.getState().setAccessLevelAgencyChoice(choices);
      return;
    }
    useAuthStore.getState().setSession(confirmedUser);
    navigateToAccessLevel(confirmedUser);
  } catch (error) {
    if (!isCurrent()) return;
    // An interrupted POST can still have changed the cookie. Keep protected
    // content unmounted until the server confirms the resulting access level.
    useAuthStore.getState().failAccessLevelChange(errorMessage(mutationError ?? error));
  }
}

export async function synchronizeAccessLevel() {
  const state = useAuthStore.getState();
  if (state.isChangingAccessLevel) return;
  state.beginAccessLevelChange();
  const expectedVersion = useAuthStore.getState().sessionVersion;
  await clearSensitiveBrowserState("access_level_changed", false);
  try {
    const user = await authApi.getMe();
    if (useAuthStore.getState().sessionVersion !== expectedVersion) return;
    useAuthStore.getState().setSession(user);
    navigateToAccessLevel(user);
  } catch (error) {
    if (useAuthStore.getState().sessionVersion !== expectedVersion) return;
    useAuthStore.getState().failAccessLevelChange(errorMessage(error));
  }
}
