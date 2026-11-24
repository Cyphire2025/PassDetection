"use client";

import { Button } from "@/components/ui/button";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useWhatsAppTemplateSettings } from "../hooks/use-whatsapp-template-settings";
import { WhatsAppTemplateNameField } from "./whatsapp-template-name-field";
import { WhatsAppTemplateSaveFeedback } from "./whatsapp-template-save-feedback";

export function WhatsAppTemplateSettingsPanel({ active }: { active: boolean }) {
  const controller = useWhatsAppTemplateSettings(active);
  const { query, settings, canView, canEdit, busy, isReloading, hasConflict, reloadLatest } = controller;
  if (!canView) return null;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 p-6">
        <div className="max-w-2xl">
          <h2 className="text-base font-semibold text-slate-950">WhatsApp templates</h2>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            Manage the approved Meta template names used across the platform. Saved names take
            priority over the environment defaults. Already queued messages keep their saved template.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={reloadLatest}
          disabled={busy}
          isLoading={isReloading}
          leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
        >
          Reload latest values
        </Button>
      </div>

      {!settings ? (
        <div className="p-6" role="status">
          {query.isError ? (
            <p className="text-sm text-red-700">Could not load template settings. Reload to try again.</p>
          ) : (
            <p className="text-sm text-slate-500">Loading current template names…</p>
          )}
        </div>
      ) : (
        <>
          <div className="space-y-3 p-6 pb-0">
            <p className="rounded-lg bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900">
              Use a Meta-approved template with the same language, variables and media format.
              Changing the name preserves delivery history and existing resend rules.
            </p>
            {!canEdit && (
              <p className="text-sm text-slate-500">Only a super administrator can change these platform-wide settings.</p>
            )}
            {hasConflict && (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                A newer version is available. Reloading replaces your unsaved changes with the latest saved values.
              </p>
            )}
            {query.isError && (
              <p role="status" className="text-sm text-amber-800">The last refresh failed. The values below are the last loaded version.</p>
            )}
          </div>

          <div className="divide-y divide-slate-100 px-6">
            {settings.templates.map((template) => (
              <WhatsAppTemplateNameField key={template.key} template={template} controller={controller} />
            ))}
          </div>

          <WhatsAppTemplateSaveFeedback controller={controller} />
        </>
      )}
    </section>
  );
}
