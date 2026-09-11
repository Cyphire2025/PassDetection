"use client";

import { useEffect, useId, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { truncate } from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { SwitchableAccessLevel, User } from "@/types";
import { changeAccessLevel } from "../services/access-level";

const ACCESS_LEVELS: ReadonlyArray<{ role: SwitchableAccessLevel; label: string }> = [
  { role: "super_admin", label: "Superadmin" },
  { role: "agency_manager", label: "Manager" },
  { role: "agency_staff", label: "Staff" },
  { role: "agency_coordinator", label: "Coordinator" },
];

export function canSwitchAccessLevel(user: User | null | undefined): boolean {
  return Boolean(user?.is_active && user.actual_role === "super_admin" && user.can_switch_access_level);
}

export function AccessLevelSwitcher() {
  const user = useAuthStore(selectUser);
  const error = useAuthStore((state) => state.accessLevelError);
  const agencyChoice = useAuthStore((state) => state.accessLevelAgencyChoice);
  const agencySelectId = useId();
  const queryClient = useQueryClient();
  const detailsRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !detailsRef.current?.contains(event.target)) {
        detailsRef.current?.removeAttribute("open");
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && detailsRef.current?.open) {
        detailsRef.current.removeAttribute("open");
        detailsRef.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  if (!user || !canSwitchAccessLevel(user)) return null;
  const currentLabel = ACCESS_LEVELS.find((level) => level.role === user.role)?.label ?? "Superadmin";

  return (
    <details ref={detailsRef} open={Boolean(error)} className="relative">
      <summary aria-label={`Change access level, currently ${currentLabel}`}
        className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-blue-600 [&::-webkit-details-marker]:hidden">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
          {user.full_name.charAt(0).toUpperCase()}
        </span>
        <span className="leading-tight">
          <span className="hidden text-xs font-medium text-slate-800 sm:block">{truncate(user.full_name, 22)}</span>
          <span className="block text-[11px] font-medium text-blue-700">{currentLabel}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
        <p className="px-3 pt-2 text-xs font-semibold text-slate-900">Access level</p>
        <p className="px-3 pb-2 pt-1 text-xs leading-5 text-slate-500">
          Same account, selected role permissions.
          {user.access_level_agency_name ? <span className="block truncate">{user.access_level_agency_name}</span> : null}
        </p>
        <div role="group" aria-label="Access levels">
          {ACCESS_LEVELS.map(({ role, label }) => (
            <button key={role} type="button" aria-pressed={role === user.role}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:cursor-default disabled:bg-blue-50 disabled:text-blue-700"
              disabled={role === user.role}
              onClick={() => void changeAccessLevel(role, queryClient)}>
              {label}
              {role === user.role ? <Check className="h-4 w-4" aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
        {error ? <p role="alert" className="px-3 py-2 text-xs leading-5 text-red-700">{error}</p> : null}
        {agencyChoice ? (
          agencyChoice.agencies.length > 0 ? (
            <div className="px-3 pb-2">
              <label htmlFor={agencySelectId} className="text-xs font-medium text-slate-700">Agency workspace</label>
              <select id={agencySelectId} defaultValue=""
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm text-slate-800"
                onChange={(event) => {
                  if (event.target.value) void changeAccessLevel(agencyChoice.role, queryClient, event.target.value);
                }}>
                <option value="" disabled>Select agency to continue</option>
                {agencyChoice.agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
              </select>
            </div>
          ) : <p className="px-3 pb-2 text-xs leading-5 text-slate-600">No active agency is available. An active agency is needed for office access levels.</p>
        ) : null}
      </div>
    </details>
  );
}

export function CoordinatorAccessLevelBar() {
  const user = useAuthStore(selectUser);
  if (!canSwitchAccessLevel(user)) return null;
  return (
    <div className="sticky top-0 z-40 border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-lg items-center justify-between px-4 py-2">
        <span className="text-xs font-medium text-slate-500">Access level</span>
        <AccessLevelSwitcher />
      </div>
    </div>
  );
}
