"use client";

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { capturePrivateOperationOwner, RequestOwnerChangedError } from "@/lib/api/request-owner";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  templateNameError,
  type WhatsAppTemplateKey,
  type WhatsAppTemplateOverrides,
  type WhatsAppTemplateSettings
} from "../whatsapp-template-settings";

interface TemplateDraft {
  base: WhatsAppTemplateSettings;
  overrides: WhatsAppTemplateOverrides;
}

export function useWhatsAppTemplateSettings(active: boolean) {
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
      const owner = capturePrivateOperationOwner();
      // An older GET must not replace the authoritative save response.
      await queryClient.cancelQueries({ queryKey, exact: true });
      owner.assertCurrent();
      const { data } = await apiClient.put<WhatsAppTemplateSettings>(
        API_ENDPOINTS.admin.whatsappTemplates,
        { expected_revision: draft.base.revision, overrides: draft.overrides },
        { ...owner.requestConfig, signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      owner.assertCurrent();
      await queryClient.cancelQueries({ queryKey, exact: true });
      if (controller.signal.aborted) return;
      owner.assertCurrent();
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
      if (controller.signal.aborted || error instanceof RequestOwnerChangedError) return;
      const apiError = error as {
        code?: string;
        message?: string;
        status?: number
      };
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

  return {
    query,
    settings,
    overrides,
    canView,
    canEdit,
    busy,
    isSaving,
    isReloading,
    hasChanges,
    hasConflict,
    invalid,
    saveError,
    saveMessage,
    updateOverride,
    reloadLatest,
    save
  };
}

export type WhatsAppTemplateSettingsController = ReturnType<typeof useWhatsAppTemplateSettings>;
