"use client";

import { X, Copy, Check } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import {
  getPassportUploadTargets,
  type PassportUploadTarget,
} from "@/lib/utils/public-url";
import { createUploadLinkSchema, type CreateUploadLinkFormData } from "../schemas/upload-link.schema";
import { useCreateUploadLink } from "../hooks/use-upload-links";
import { GroupOptionToggle } from "./group-option-toggle";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";

interface CreateUploadLinkModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateUploadLinkModal({ isOpen, onClose }: CreateUploadLinkModalProps) {
  const [generatedTargets, setGeneratedTargets] = useState<PassportUploadTarget[]>([]);
  const [copiedTargetKey, setCopiedTargetKey] = useState<string | null>(null);
  const [cityInput, setCityInput] = useState("");
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
      departure_cities: [],
      base_city_enabled: false,
      nearest_international_airport_enabled: false,
      staff_code_enabled: false,
      meal_preference_enabled: false,
      require_selfie: false,
      allow_files_from_device: true,
      ask_nearest_domestic_airport: false,
      relation_with_qualifier_enabled: false,
      whatsapp_broadcast_group_ids: [],
      notes: "",
    },
  });
  const departureCities = useWatch({ control, name: "departure_cities" }) ?? [];
  const baseCityEnabled = useWatch({ control, name: "base_city_enabled" }) ?? false;
  const airportEnabled = useWatch({ control, name: "nearest_international_airport_enabled" }) ?? false;
  const staffCodeEnabled = useWatch({ control, name: "staff_code_enabled" }) ?? false;
  const mealPreferenceEnabled = useWatch({ control, name: "meal_preference_enabled" }) ?? false;
  const requireSelfie = useWatch({ control, name: "require_selfie" }) ?? false;
  const allowFilesFromDevice = useWatch({ control, name: "allow_files_from_device" }) ?? true;
  const askNearestDomesticAirport = useWatch({ control, name: "ask_nearest_domestic_airport" }) ?? false;
  const relationWithQualifierEnabled = useWatch({
    control,
    name: "relation_with_qualifier_enabled",
  }) ?? false;
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
    setCityInput("");
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
        destination: data.destination || null,
        travel_date: data.travel_date || null,
        return_date: data.return_date || null,
        departure_cities: data.nearest_international_airport_enabled
          ? normalizeCities(data.departure_cities)
          : [],
        notes: data.notes || null,
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

  const addCity = () => {
    const nextCity = normalizeCity(cityInput);
    if (!nextCity) return;
    const nextCities = normalizeCities([...departureCities, nextCity]);
    setValue("departure_cities", nextCities, { shouldDirty: true, shouldValidate: true });
    setCityInput("");
  };

  const removeCity = (city: string) => {
    setValue(
      "departure_cities",
      departureCities.filter((item) => item !== city),
      { shouldDirty: true, shouldValidate: true },
    );
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
              <Input
                label="Group Name"
                placeholder="e.g. Summer Europe Tour 2026"
                {...register("name")}
                error={errors.name?.message}
                autoFocus
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <Input label="Destination" placeholder="e.g. Dubai" {...register("destination")} />
                <Input label="Travel Date" type="date" {...register("travel_date")} />
                <Input label="Return Date" type="date" {...register("return_date")} />
              </div>

              <div className="space-y-1">
                <label htmlFor="create-upload-link-notes" className="text-sm font-medium text-slate-700">Notes</label>
                <textarea
                  id="create-upload-link-notes"
                  {...register("notes")}
                  rows={3}
                  placeholder="Internal notes for this group"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div className="space-y-3">
                <GroupOptionToggle
                  label="Allow files from device"
                  description="Let travellers choose existing passport images from their gallery or file picker in addition to using the live scanner."
                  checked={allowFilesFromDevice}
                  onChange={(checked) => setValue("allow_files_from_device", checked, { shouldDirty: true })}
                />
                <GroupOptionToggle
                  label="Ask for nearest domestic airport"
                  description="Require each traveller to enter their nearest domestic airport during passport review."
                  checked={askNearestDomesticAirport}
                  onChange={(checked) => setValue("ask_nearest_domestic_airport", checked, { shouldDirty: true })}
                />
                <GroupOptionToggle
                  label="Visa Photo Upload"
                  description="Require each traveller to capture a Visa Photo against a plain white or off-white wall."
                  checked={requireSelfie}
                  onChange={(checked) => setValue("require_selfie", checked, { shouldDirty: true })}
                />
                <GroupOptionToggle
                  label="Relation with Qualifier"
                  description="Enable a required Self or approved family-relationship choice before this single-passenger upload flow begins."
                  checked={relationWithQualifierEnabled}
                  onChange={(checked) => setValue(
                    "relation_with_qualifier_enabled",
                    checked,
                    { shouldDirty: true },
                  )}
                />
                <GroupOptionToggle
                  label="Base City"
                  description="Require each client to enter the city where they reside."
                  checked={baseCityEnabled}
                  onChange={(checked) => setValue("base_city_enabled", checked, { shouldDirty: true })}
                />

                <div className={`rounded-xl border p-4 transition-colors ${airportEnabled ? "border-blue-200 bg-blue-50/40" : "border-slate-200 bg-white"}`}>
                  <GroupOptionToggle
                    label="Nearest International Airport"
                    description="Require clients to select one airport from your list."
                    checked={airportEnabled}
                    onChange={(checked) => {
                      setValue("nearest_international_airport_enabled", checked, { shouldDirty: true, shouldValidate: true });
                      if (!checked) {
                        setValue("departure_cities", [], { shouldDirty: true, shouldValidate: true });
                        setCityInput("");
                      }
                    }}
                    borderless
                  />
                  {airportEnabled && (
                    <div className="mt-4 space-y-2 border-t border-slate-100 pt-4">
                      <div className="flex gap-2">
                        <Input
                          value={cityInput}
                          onChange={(event) => setCityInput(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              addCity();
                            }
                          }}
                          placeholder="e.g. Delhi, Chennai, Mumbai"
                        />
                        <Button type="button" variant="secondary" onClick={addCity}>
                          Add
                        </Button>
                      </div>
                      {departureCities.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {departureCities.map((city) => (
                            <button
                              key={city}
                              type="button"
                              onClick={() => removeCity(city)}
                              className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800 transition hover:bg-blue-100"
                            >
                              {city}
                              <X className="h-3 w-3" aria-hidden="true" />
                            </button>
                          ))}
                        </div>
                      )}
                      {errors.departure_cities && <p className="text-xs text-red-500">{errors.departure_cities.message}</p>}
                    </div>
                  )}
                </div>

                <GroupOptionToggle
                  label="Staff Code"
                  description="Require each client to enter their staff code."
                  checked={staffCodeEnabled}
                  onChange={(checked) => setValue("staff_code_enabled", checked, { shouldDirty: true })}
                />
                <GroupOptionToggle
                  label="Meal Preference"
                  description="Require each client to choose Veg, Non Veg, or Jain."
                  checked={mealPreferenceEnabled}
                  onChange={(checked) => setValue("meal_preference_enabled", checked, { shouldDirty: true })}
                />
              </div>

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
