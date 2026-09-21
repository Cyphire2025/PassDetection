"use client";

import { Button } from "@/components/ui/button";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, RefreshCw, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  templateNameError,
  WHATSAPP_TEMPLATE_NAME_MAX_LENGTH,
  type WhatsAppTemplateKey,
  type WhatsAppTemplateOverrides,
  type WhatsAppTemplateSettings,
} from "../whatsapp-template-settings";

interface TemplateDraft {
  base: WhatsAppTemplateSettings;
  overrides: WhatsAppTemplateOverrides;
}

export function WhatsAppTemplateSettingsPanel({ active }: { active: boolean }) {
  const user = useAuthStore(selectUser);
  const queryClient = useQueryClient();
  const queryKey = ["settings", "whatsapp-templates", user?.id, user?.role] as const;
  const [draft, setDraft] = useState<TemplateDraft | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isReloading, setIsReloading] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const saveController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const canView = user?.role === "super_admin" || user?.role === "agency_admin";

  const query = useQuery({
    queryKey,
    enabled: active && canView && !isSaving,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.get<WhatsAppTemplateSettings>(
        API_ENDPOINTS.admin.whatsappTemplates,
        { signal },
      );
      const current = queryClient.getQueryData<WhatsAppTemplateSettings>(queryKey);
      return current && current.revision > data.revision ? current : data;
    },
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      saveController.current?.abort();
    };
  }, []);

  // Anchor edits to the version the administrator actually reviewed. Background
  // refreshes can report a conflict, but must never overwrite their draft.
  const settings = draft?.base ?? query.data;
  const overrides = draft?.overrides ?? {};
  const hasChanges = Object.keys(overrides).length > 0;
  const hasConflict = conflict || Boolean(
    draft && query.data && draft.base.revision !== query.data.revision,
  );
  const canEdit = user?.role === "super_admin" && query.data?.can_edit === true;
  const invalid = Object.values(overrides).some(
    (value) => value !== undefined && templateNameError(value) !== null,
  );
  const busy = isSaving || isReloading;

  function updateOverride(key: WhatsAppTemplateKey, value: string | null) {
    if (!settings || !canEdit || busy) return;
    const template = settings.templates.find((item) => item.key === key);
    if (!template) return;
    const next = { ...overrides };
    const nextValue = template.override_name === null && value === template.environment_name
      ? null
      : value;
    if (nextValue === template.override_name) delete next[key];
    else next[key] = nextValue;
    setDraft(Object.keys(next).length ? { base: settings, overrides: next } : null);
    setSaveError(null);
    setSaveMessage(null);
  }

  async function reloadLatest() {
    if (busy) return;
    setIsReloading(true);
    setSaveError(null);
    try {
      await query.refetch({ throwOnError: true });
      if (!mounted.current) return;
      setDraft(null);
      setConflict(false);
      setSaveMessage(null);
    } catch {
      if (mounted.current) setSaveError("Could not reload template settings. Your changes are still here.");
    } finally {
      if (mounted.current) setIsReloading(false);
    }
  }

  async function save() {
    if (!draft || !canEdit || busy || hasConflict || invalid || saveController.current) return;
    const controller = new AbortController();
    saveController.current = controller;
    setIsSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      // An older GET must not replace the authoritative save response.
      await queryClient.cancelQueries({ queryKey, exact: true });
      const { data } = await apiClient.put<WhatsAppTemplateSettings>(
        API_ENDPOINTS.admin.whatsappTemplates,
        { expected_revision: draft.base.revision, overrides: draft.overrides },
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      await queryClient.cancelQueries({ queryKey, exact: true });
      if (controller.signal.aborted) return;
      queryClient.setQueryData<WhatsAppTemplateSettings>(queryKey, (current) =>
        current && current.revision > data.revision ? current : data,
      );
      setDraft(null);
      setConflict(false);
      setSaveMessage("Template settings saved. New sends will use these names.");
      // Cache refresh is independent of the committed save and must not turn a
      // successful update into a misleading save error if another screen fails.
      void Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: ["whatsapp"] }),
        queryClient.invalidateQueries({ queryKey: ["document-distribution"] }),
        queryClient.invalidateQueries({ queryKey: ["operations", "tour-operations"] }),
      ]);
    } catch (error) {
      if (controller.signal.aborted) return;
      const apiError = error as { code?: string; message?: string; status?: number };
      if (apiError.code === "WHATSAPP_TEMPLATE_REVISION_CONFLICT" || apiError.status === 409) {
        setConflict(true);
        setSaveError("Template settings changed since you opened them. Your draft has been kept. Reload the latest values before editing again.");
      } else {
        setSaveError(apiError.message || "Could not confirm the save. Your changes are still here; reload the latest values before retrying.");
      }
    } finally {
      if (saveController.current === controller) saveController.current = null;
      if (mounted.current) setIsSaving(false);
    }
  }

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
        <Button type="button" variant="secondary" size="sm" onClick={reloadLatest}
          disabled={busy} isLoading={isReloading} leftIcon={<RefreshCw className="h-3.5 w-3.5" />}>
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
              <p role="alert" className="flex items-start gap-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                A newer version is available. Reloading replaces your unsaved changes with the latest saved values.
              </p>
            )}
            {query.isError && (
              <p role="status" className="text-sm text-amber-800">The last refresh failed. The values below are the last loaded version.</p>
            )}
          </div>

          <div className="divide-y divide-slate-100 px-6">
            {settings.templates.map((template) => {
              const changed = Object.prototype.hasOwnProperty.call(overrides, template.key);
              const selectedOverride = changed ? overrides[template.key] ?? null : template.override_name;
              const value = selectedOverride ?? template.environment_name;
              const error = changed ? templateNameError(selectedOverride) : null;
              const fieldId = `whatsapp-template-${template.key}`;
              return (
                <div key={template.key} className="grid gap-3 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:gap-8">
                  <div>
                    <label htmlFor={fieldId} className="text-sm font-semibold text-slate-800">{template.label}</label>
                    <p id={`${fieldId}-description`} className="mt-1 text-xs leading-5 text-slate-500">{template.contract_description}</p>
                    <p className="mt-2 text-xs text-slate-500">Language: <span className="font-medium text-slate-700">{template.language || "Not configured"}</span></p>
                  </div>
                  <div className="min-w-0 space-y-2">
                    <input id={fieldId} type="text" value={value} autoComplete="off" spellCheck={false}
                      autoCapitalize="none" maxLength={WHATSAPP_TEMPLATE_NAME_MAX_LENGTH}
                      placeholder="Not configured" disabled={!canEdit || busy || hasConflict}
                      aria-invalid={Boolean(error)}
                      aria-describedby={`${fieldId}-description${error ? ` ${fieldId}-error` : ""}`}
                      onChange={(event) => updateOverride(template.key, event.target.value)}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 font-mono text-sm text-slate-800 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-500"
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className={`text-xs ${changed ? "text-amber-700" : "text-slate-500"}`}>
                        {changed ? "Unsaved · " : ""}{selectedOverride === null ? "Environment default" : "Settings override"}
                      </span>
                      {canEdit && selectedOverride !== null && (
                        <Button type="button" variant="link" size="sm" disabled={busy || hasConflict}
                          onClick={() => updateOverride(template.key, null)}>Use environment default</Button>
                      )}
                    </div>
                    {selectedOverride !== null && (
                      <p className="break-all text-xs text-slate-500">Environment default: {template.environment_name || "Not configured"}</p>
                    )}
                    {error && <p id={`${fieldId}-error`} className="text-xs text-red-700">{error}</p>}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 bg-slate-50/50 px-6 py-4">
            <div className="min-w-0 flex-1 text-sm" aria-live="polite">
              {saveError ? <p className="text-red-700" role="alert">{saveError}</p> : saveMessage ? (
                <p className="flex items-center gap-2 text-emerald-700"><Check className="h-4 w-4 shrink-0" />{saveMessage}</p>
              ) : (
                <p className="text-slate-500">{hasChanges ? "You have unsaved template changes. Reloading will discard them." : "Changes apply to new sends after saving."}</p>
              )}
            </div>
            {canEdit && (
              <Button type="button" onClick={save} isLoading={isSaving}
                disabled={!hasChanges || invalid || hasConflict || busy}
                leftIcon={<Save className="h-4 w-4" />}>Save template settings</Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
