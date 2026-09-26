"use client";

import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { AccountSecurityPanel } from "@/features/auth/components/account-security-panel";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  Database,
  MessageSquare,
  Monitor,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";
import dynamic from "next/dynamic";
import { AppearanceSettings } from "./appearance-settings";
import { PlatformSettingsPanel } from "./platform-settings-panel";

const WhatsAppTemplateSettingsPanel = dynamic(
  () => import("./whatsapp-template-settings-panel").then(
    (module) => module.WhatsAppTemplateSettingsPanel,
  ),
  {
    loading: () => (
      <div role="status" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
        Loading WhatsApp template settings…
      </div>
    ),
  },
);

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
    id: "whatsapp",
    title: "WhatsApp templates",
    description: "Approved message template names",
    icon: MessageSquare,
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
  const [templatesVisited, setTemplatesVisited] = useState(false);
  const user = useAuthStore(selectUser);
  const canViewTemplates = user?.role === "super_admin" || user?.role === "agency_admin";
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
          {SECTIONS.filter(({ id }) => id !== "whatsapp" || canViewTemplates).map(({ id, title, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={section === id ? "page" : undefined}
              onClick={() => {
                setSection(id);
                if (id === "whatsapp") setTemplatesVisited(true);
              }}
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
          <VisitedTemplateSettings
            visited={templatesVisited}
            authorized={canViewTemplates}
            active={section === "whatsapp"}
            userId={user?.id}
          />
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

function VisitedTemplateSettings({ visited, authorized, active, userId }: {
  visited: boolean;
  authorized: boolean;
  active: boolean;
  userId?: string;
}) {
  if (!visited || !authorized) return null;
  return (
    <div hidden={!active}>
      <WhatsAppTemplateSettingsPanel key={userId} active={active} />
    </div>
  );
}
