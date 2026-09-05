"use client";

import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { AccountSecurityPanel } from "@/features/auth/components/account-security-panel";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  Check,
  Database,
  Monitor,
  PanelLeft,
  RotateCcw,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";
import { useDashboardPreferences } from "../dashboard-preferences";
import { PlatformSettingsPanel } from "./platform-settings-panel";

const SECTIONS = [
  {
    id: "appearance",
    title: "Appearance & navigation",
    description: "Display and sidebar preferences",
    icon: Monitor,
  },
  {
    id: "policies",
    title: "Platform policies",
    description: "Intake, review and retention",
    icon: SlidersHorizontal,
  },
  {
    id: "security",
    title: "Account & security",
    description: "Your identity and active sessions",
    icon: ShieldCheck,
  },
  {
    id: "data",
    title: "Data administration",
    description: "Manage retained operational data",
    icon: Database,
  },
] as const;
type Section = (typeof SECTIONS)[number]["id"];

export function DashboardSettingsPage() {
  const [section, setSection] = useState<Section>("appearance");
  const user = useAuthStore(selectUser);
  return (
    <div className="space-y-5">
      <WorkspacePageHeader
        title="Settings"
        description="Manage display preferences, platform policies, and account security."
        icon={Settings2}
      />
      <div className="grid items-start gap-8 xl:grid-cols-[235px_minmax(0,1fr)]">
        <nav
          aria-label="Settings sections"
          className="grid gap-1 sm:grid-cols-2 xl:sticky xl:top-0 xl:grid-cols-1"
        >
          {SECTIONS.map(({ id, title, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={section === id ? "page" : undefined}
              onClick={() => setSection(id)}
              className={`flex items-start gap-3 rounded-xl px-4 py-3.5 text-left transition ${section === id ? "bg-white shadow-sm ring-1 ring-slate-200" : "hover:bg-slate-100"}`}
            >
              <Icon
                className={`mt-0.5 h-4 w-4 shrink-0 ${section === id ? "text-blue-700" : "text-slate-400"}`}
              />
              <span>
                <span className="block text-[13px] font-semibold text-slate-800">
                  {title}
                </span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">
                  {description}
                </span>
              </span>
            </button>
          ))}
        </nav>
        <div className="min-w-0" aria-live="polite">
          {section === "appearance" && <AppearanceSettings />}
          {/* Preserve policy drafts while another settings section is open. */}
          <div hidden={section !== "policies" && section !== "data"}>
            <PlatformSettingsPanel
              section={section === "data" ? "data" : "policies"}
            />
          </div>
          {section === "security" && (
            <div className="space-y-6">
              <section className="rounded-xl border border-slate-200 bg-white p-6">
                <h2 className="text-base font-semibold text-slate-950">
                  Your account
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Account details and access role.
                </p>
                <dl className="mt-5 grid gap-5 sm:grid-cols-2">
                  {[
                    ["Name", user?.full_name],
                    ["Email address", user?.email],
                    ["Role", user?.role.replaceAll("_", " ")],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-xs text-slate-500">{label}</dt>
                      <dd className="mt-1 break-words text-sm font-medium capitalize text-slate-800">
                        {value ?? "Unavailable"}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
              <AccountSecurityPanel />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AppearanceSettings() {
  const preferences = useDashboardPreferences();
  const update = preferences.update;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-6">
        <div>
          <h2 className="text-base font-semibold text-slate-950">
            Appearance & navigation
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Changes apply immediately and are saved in this browser.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700">
          <Check className="h-3.5 w-3.5" /> Saved automatically
        </span>
      </div>
      <div className="divide-y divide-slate-100 px-6">
        <PreferenceRow
          title="Table density"
          description="Adjust spacing in passenger, document, and activity tables."
        >
          <Choice
            label="Table density"
            value={preferences.density}
            options={[
              ["comfortable", "Comfortable"],
              ["compact", "Compact"],
            ]}
            onChange={(density) => update({ density })}
          />
        </PreferenceRow>
        <PreferenceRow
          title="Workspace width"
          description="Use the full available width or a narrower content area."
        >
          <Choice
            label="Workspace width"
            value={preferences.contentWidth}
            options={[
              ["wide", "Wide"],
              ["focused", "Focused"],
            ]}
            onChange={(contentWidth) => update({ contentWidth })}
          />
        </PreferenceRow>
        <PreferenceRow
          title="Text size"
          description="Increase table and supporting text without changing your browser zoom."
        >
          <Choice
            label="Text size"
            value={preferences.textSize}
            options={[
              ["standard", "Standard"],
              ["large", "Larger"],
            ]}
            onChange={(textSize) => update({ textSize })}
          />
        </PreferenceRow>
        <PreferenceRow
          title="Compact navigation"
          description="Show sidebar icons without labels."
        >
          <Toggle
            label="Compact navigation"
            checked={preferences.sidebarCollapsed}
            onChange={(sidebarCollapsed) => update({ sidebarCollapsed })}
          />
        </PreferenceRow>
        <PreferenceRow
          title="Reduce motion"
          description="Minimise transitions and animations throughout the dashboard. Your device accessibility preference is always respected."
        >
          <Toggle
            label="Reduce motion"
            checked={preferences.reduceMotion}
            onChange={(reduceMotion) => update({ reduceMotion })}
          />
        </PreferenceRow>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 bg-slate-50/50 px-6 py-4">
        <p className="flex items-center gap-2 text-xs text-slate-500">
          <PanelLeft className="h-4 w-4" /> Open global search with{" "}
          <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.5">
            Ctrl / ⌘ K
          </kbd>
        </p>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={preferences.reset}
          leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
        >
          Reset appearance
        </Button>
      </div>
    </section>
  );
}

function PreferenceRow({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col justify-between gap-4 py-6 sm:flex-row sm:items-center">
      <div className="max-w-md">
        <h3 className="text-sm font-medium text-slate-800">{title}</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex gap-1 rounded-lg bg-slate-100 p-1"
    >
      {options.map(([key, text]) => (
        <button
          key={key}
          type="button"
          aria-pressed={key === value}
          onClick={() => onChange(key)}
          className={`min-w-20 rounded-md px-3 py-2 text-xs font-medium transition ${key === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-blue-700" : "bg-slate-300"}`}
    >
      <span
        className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-5" : ""}`}
      />
    </button>
  );
}
