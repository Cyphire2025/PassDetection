"use client";

import { useEffect, useRef, useState } from "react";
import {
  buildPlatformSettingsUpdate,
  conflictCurrentUpdatedAt,
  DEFAULT_PLATFORM_SETTINGS,
  isPlatformSettingsRevisionConflict,
  type PlatformSettings,
} from "../platform-settings-policy";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";

type SettingsLoadState = "loading" | "ready" | "error" | "conflict";

export function usePlatformSettings() {
  const user = useAuthStore(selectUser);
  const [settings, setSettings] = useState<PlatformSettings>(
    DEFAULT_PLATFORM_SETTINGS,
  );
  const [authoritativeUpdatedAt, setAuthoritativeUpdatedAt] = useState<
    string | null
  >(null);
  const [loadState, setLoadState] = useState<SettingsLoadState>("loading");
  const [loadRequest, setLoadRequest] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const isLoading = loadState === "loading";
  const isAuthorityReady = loadState === "ready" && user !== null;
  const isSuperAdmin = user?.role === "super_admin";
  const canEditPolicies = isAuthorityReady && isSuperAdmin;
  const canPurge =
    isAuthorityReady &&
    (isSuperAdmin || user.role === "agency_admin");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    apiClient
      .get<PlatformSettings>(API_ENDPOINTS.admin.settings, {
        signal: controller.signal,
      })
      .then(({ data }) => {
        if (!active) return;
        setSettings(data);
        setAuthoritativeUpdatedAt(data.updated_at);
        setLoadState("ready");
      })
      .catch(() => {
        if (!active) return;
        setLoadError(
          "Could not load authoritative platform settings. Editing and destructive actions remain unavailable until the server state is loaded.",
        );
        setLoadState("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [loadRequest]);

  const updateSetting = <K extends keyof PlatformSettings>(
    key: K,
    value: PlatformSettings[K],
  ) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const saveInFlight = useRef(false);
  const handleSave = async () => {
    if (!canEditPolicies || isSaving || saveInFlight.current) return;
    saveInFlight.current = true;
    setIsSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const payload = buildPlatformSettingsUpdate(
        settings,
        authoritativeUpdatedAt,
      );
      const { data } = await apiClient.put<PlatformSettings>(
        API_ENDPOINTS.admin.settings,
        payload,
      );
      setSettings(data);
      setAuthoritativeUpdatedAt(data.updated_at);
      setSaveMessage("Settings saved.");
    } catch (error) {
      if (isPlatformSettingsRevisionConflict(error)) {
        const currentUpdatedAt = conflictCurrentUpdatedAt(error);
        const revisionMessage = currentUpdatedAt
          ? ` The server reports a newer revision saved ${formatDateTime(currentUpdatedAt)}.`
          : " The server state no longer matches the version that was loaded.";
        setLoadState("conflict");
        setSaveError(
          `Platform settings changed before this save completed.${revisionMessage} Your edits are preserved here; reload the authoritative settings before editing or saving again.`,
        );
      } else {
        setSaveError(
          "Could not save settings. Your edits are still present and were not reported as saved.",
        );
      }
    } finally {
      saveInFlight.current = false;
      setIsSaving(false);
    }
  };

  const reloadAuthoritativeSettings = () => {
    if (
      loadState === "conflict" &&
      !window.confirm(
        "Reload the authoritative platform settings? This replaces the unsaved edits currently shown on this page.",
      )
    ) {
      return;
    }
    setLoadState("loading");
    setLoadError(null);
    setSaveError(null);
    setSaveMessage(null);
    setLoadRequest((current) => current + 1);
  };

  const settingsStatusLabel =
    loadState === "loading"
      ? "Loading saved policy"
      : loadState === "error"
        ? "Settings unavailable"
        : loadState === "conflict"
          ? "Reload required"
          : settings.updated_at
            ? `Saved ${formatDateTime(settings.updated_at)}`
            : "No saved policy yet";

  return {
    settings, loadState, loadError, isLoading, isAuthorityReady, isSuperAdmin,
    canEditPolicies, canPurge, isSaving, saveError, saveMessage,
    settingsStatusLabel, updateSetting, handleSave, reloadAuthoritativeSettings,
  };
}

export type PlatformSettingsController = ReturnType<typeof usePlatformSettings>;
