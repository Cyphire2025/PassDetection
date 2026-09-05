"use client";

import { X, Copy, Check } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import {
  getPassportUploadTargets,
  type PassportUploadTarget,
} from "@/lib/utils/public-url";
import { createUploadLinkSchema, type CreateUploadLinkFormData } from "../schemas/upload-link.schema";
import { useCreateUploadLink } from "../hooks/use-upload-links";
import { getUploadLinkSettings, getUploadLinkSettingsError, UploadLinkSettings, type UploadLinkSettingsValue } from "./upload-link-settings";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";
import { TripTimeZoneField } from "./trip-timezone-field";
import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";

interface CreateUploadLinkModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateUploadLinkModal({ isOpen, onClose }: CreateUploadLinkModalProps) {
  const role = useAuthStore(selectUserRole);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);
  const [generatedTargets, setGeneratedTargets] = useState<PassportUploadTarget[]>([]);
  const [copiedTargetKey, setCopiedTargetKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const copiedTimerRef = useRef<number | null>(null);
  const titleId = useId();
  const { tryEnter: tryEnterCreate, leave: leaveCreate } = useSingleFlightGate();
  const { mutateAsync: createUploadLink, isPending } = useCreateUploadLink();

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<CreateUploadLinkFormData>({
    resolver: zodResolver(createUploadLinkSchema),
    defaultValues: {
      name: "",
      destination: "",
      travel_date: "",
      return_date: "",
      timezone: DEFAULT_TRIP_TIMEZONE,
      departure_cities: [],
      base_city_enabled: false,
      nearest_international_airport_enabled: false,
      staff_code_enabled: false,
      agent_employee_code_enabled: false,
      meal_preference_enabled: false,
      require_selfie: false,
      allow_files_from_device: true,
      ask_nearest_domestic_airport: false,
      relation_with_qualifier_enabled: false,
      designation_enabled: false,
      agency_dealership_name_enabled: false,
      custom_questions: [],
      custom_details: [],
      whatsapp_broadcast_group_ids: [],
      upload_configuration: getUploadLinkSettings({}).upload_configuration,
    },
  });
  const settings = useWatch({ control, compute: (values) => getUploadLinkSettings(values) });
  const whatsappBroadcastGroupIds = useWatch({
    control,
    name: "whatsapp_broadcast_group_ids",
  }) ?? [];

  useEffect(() => () => {
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
  }, []);

  const handleClose = useCallback(() => {
    if (isPending) return;
    if (copiedTimerRef.current !== null) {
      window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = null;
    }
    reset();
    setGeneratedTargets([]);
    setCopiedTargetKey(null);
    setActionError(null);
    onClose();
  }, [isPending, onClose, reset]);

  useEffect(() => {
    if (!isOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isPending) handleClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [handleClose, isOpen, isPending]);

  const onSubmit = async (data: CreateUploadLinkFormData) => {
    if (isPending || !tryEnterCreate()) return;
    setActionError(null);
    try {
      const result = await createUploadLink({
        ...data,
        name: data.name.trim(),
        destination: data.destination.trim(),
        travel_date: data.travel_date,
        return_date: data.return_date,
        departure_cities: data.nearest_international_airport_enabled
          ? normalizeCities(data.departure_cities)
          : [],
        whatsapp_broadcast_group_ids: canAccessWhatsApp
          ? data.whatsapp_broadcast_group_ids
          : [],
      });
      setGeneratedTargets(getPassportUploadTargets(result.token));
    } catch {
      setActionError(
        "The upload link could not be created. Check your connection and try again.",
      );
    } finally {
      leaveCreate();
    }
  };

  const copyTarget = async (target: PassportUploadTarget) => {
    setActionError(null);
    try {
      await copyTextToClipboard(target.url);
      setCopiedTargetKey(target.key);
      if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = window.setTimeout(() => {
        setCopiedTargetKey((current) => current === target.key ? null : current);
        copiedTimerRef.current = null;
      }, 2000);
    } catch {
      setActionError(
        "The link could not be copied automatically. Select the link text and copy it manually.",
      );
    }
  };

  const hasGeneratedTargets = generatedTargets.length > 0;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isPending}
        className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-slate-800">
            {hasGeneratedTargets ? "Links Generated" : "Create Upload Link"}
          </h2>
          <button
            type="button"
            onClick={handleClose}
            disabled={isPending}
            aria-label="Close create upload link dialog"
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-73px)] overflow-y-auto p-6">
          {hasGeneratedTargets ? (
            <div className="space-y-6">
              <div role="status" className="rounded-lg border border-green-100 bg-green-50 p-4 text-sm text-green-800">
                Success. The public client link is ready for sharing.
              </div>

              <div className="space-y-4">
                {generatedTargets.map((target) => (
                  <div key={target.key} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="mb-2 flex items-center justify-between">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">{target.label} Link</div>
                        <div className="text-xs text-slate-500">{target.description}</div>
                      </div>
                      <Button
                        type="button"
                        onClick={() => copyTarget(target)}
                        variant="secondary"
                        className="min-w-28"
                      >
                        {copiedTargetKey === target.key ? (
                          <>
                            <Check className="h-4 w-4 text-green-600" /> Copied
                          </>
                        ) : (
                          <>
                            <Copy className="h-4 w-4 text-slate-600" /> Copy
                          </>
                        )}
                      </Button>
                    </div>
                    <Input
                      readOnly
                      value={target.url}
                      aria-label={`${target.label} upload link`}
                      className="bg-white"
                    />
                  </div>
                ))}
              </div>

              {actionError && (
                <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}

              <Button onClick={handleClose} className="w-full">
                Done
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-900">Group Details</h3>
              <Input
                label="Group Name"
                placeholder="e.g. Summer Europe Tour 2026"
                {...register("name")}
                error={errors.name?.message}
                autoFocus
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Destination"
                  placeholder="e.g. Dubai"
                  {...register("destination")}
                  error={errors.destination?.message}
                  required
                />
                <Input
                  label="Travel/Departure Date"
                  type="date"
                  {...register("travel_date")}
                  error={errors.travel_date?.message}
                  required
                />
                <Input
                  label="Return Date"
                  type="date"
                  {...register("return_date")}
                  error={errors.return_date?.message}
                  required
                />
                <TripTimeZoneField
                  {...register("timezone")}
                  error={errors.timezone?.message}
                  required
                />
              </div>

              <UploadLinkSettings
                value={settings}
                disabled={isPending}
                error={
                  errors.upload_configuration || errors.departure_cities || errors.custom_questions || errors.custom_details
                    ? getUploadLinkSettingsError(settings)
                    : undefined
                }
                onChange={(patch) => {
                  for (const [key, value] of Object.entries(patch)) {
                    setValue(key as keyof UploadLinkSettingsValue, value, { shouldDirty: true, shouldValidate: true });
                  }
                }}
              />

              {canAccessWhatsApp && (
                <WhatsAppBroadcastSelector
                  selectedIds={whatsappBroadcastGroupIds}
                  onChange={(ids) => setValue(
                    "whatsapp_broadcast_group_ids",
                    ids,
                    { shouldDirty: true, shouldValidate: true },
                  )}
                  disabled={isPending}
                  description="Optional. Link the group to one or more existing broadcasts now so recipient submissions can be tracked from the beginning."
                />
              )}

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                This will generate:
                <div className="mt-2">1. An upload link for clients on phones or browsers</div>
              </div>

              {actionError && (
                <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}

              <div className="flex justify-end gap-3 pt-4">
                <Button type="button" variant="secondary" onClick={handleClose} disabled={isPending}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending ? "Creating..." : "Generate Links"}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function normalizeCity(value: string) {
  return value.trim().replace(/\s+/g, " ").slice(0, 120);
}

function normalizeCities(values: string[]) {
  const seen = new Set<string>();
  const cities: string[] = [];
  for (const value of values) {
    const city = normalizeCity(value);
    if (!city) continue;
    const key = city.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cities.push(city);
  }
  return cities;
}

function useSingleFlightGate() {
  const inFlightRef = useRef(false);
  const tryEnter = useCallback(() => {
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    return true;
  }, []);
  const leave = useCallback(() => {
    inFlightRef.current = false;
  }, []);
  return { tryEnter, leave };
}
