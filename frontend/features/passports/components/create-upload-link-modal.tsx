"use client";

import { X, Copy, Check } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import {
  getPassportUploadTargets,
  type PassportUploadTarget,
} from "@/lib/utils/public-url";
import { createUploadLinkSchema, type CreateUploadLinkFormData } from "../schemas/upload-link.schema";
import { useCreateUploadLink } from "../hooks/use-upload-links";

interface CreateUploadLinkModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateUploadLinkModal({ isOpen, onClose }: CreateUploadLinkModalProps) {
  const [generatedTargets, setGeneratedTargets] = useState<PassportUploadTarget[]>([]);
  const [copiedTargetKey, setCopiedTargetKey] = useState<string | null>(null);
  const [cityInput, setCityInput] = useState("");
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
      notes: "",
    },
  });
  const departureCities = useWatch({ control, name: "departure_cities" }) ?? [];
  const baseCityEnabled = useWatch({ control, name: "base_city_enabled" }) ?? false;
  const airportEnabled = useWatch({ control, name: "nearest_international_airport_enabled" }) ?? false;
  const staffCodeEnabled = useWatch({ control, name: "staff_code_enabled" }) ?? false;
  const mealPreferenceEnabled = useWatch({ control, name: "meal_preference_enabled" }) ?? false;
  const requireSelfie = useWatch({ control, name: "require_selfie" }) ?? false;

  if (!isOpen) return null;

  const onSubmit = async (data: CreateUploadLinkFormData) => {
    try {
      const result = await createUploadLink({
        ...data,
        destination: data.destination || null,
        travel_date: data.travel_date || null,
        return_date: data.return_date || null,
        departure_cities: data.nearest_international_airport_enabled
          ? normalizeCities(data.departure_cities)
          : [],
        notes: data.notes || null,
      });
      setGeneratedTargets(getPassportUploadTargets(result.token));
    } catch (error) {
      console.error("Failed to create link", error);
    }
  };

  const handleClose = () => {
    reset();
    setGeneratedTargets([]);
    setCopiedTargetKey(null);
    setCityInput("");
    onClose();
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
    await copyTextToClipboard(target.url);
    setCopiedTargetKey(target.key);
    window.setTimeout(() => {
      setCopiedTargetKey((current) => current === target.key ? null : current);
    }, 2000);
  };

  const hasGeneratedTargets = generatedTargets.length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-800">
            {hasGeneratedTargets ? "Links Generated" : "Create Upload Link"}
          </h2>
          <button
            onClick={handleClose}
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-73px)] overflow-y-auto p-6">
          {hasGeneratedTargets ? (
            <div className="space-y-6">
              <div className="rounded-lg border border-green-100 bg-green-50 p-4 text-sm text-green-800">
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
                    <Input readOnly value={target.url} className="bg-white" />
                  </div>
                ))}
              </div>

              <Button onClick={handleClose} className="w-full">
                Done
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">Group Name</label>
                <Input
                  placeholder="e.g. Summer Europe Tour 2026"
                  {...register("name")}
                  className={errors.name ? "border-red-500" : ""}
                />
                {errors.name && (
                  <p className="text-xs text-red-500">{errors.name.message}</p>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">Destination</label>
                  <Input placeholder="e.g. Dubai" {...register("destination")} />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">Travel Date</label>
                  <Input type="date" {...register("travel_date")} />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">Return Date</label>
                  <Input type="date" {...register("return_date")} />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">Notes</label>
                <textarea
                  {...register("notes")}
                  rows={3}
                  placeholder="Internal notes for this group"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div className="space-y-3">
                <FormOptionToggle
                  label="VISA Selfie Photo"
                  description="Require each client to capture a passport-size selfie against a plain white wall."
                  checked={requireSelfie}
                  onChange={(checked) => setValue("require_selfie", checked, { shouldDirty: true })}
                />
                <FormOptionToggle
                  label="Base City"
                  description="Require each client to enter the city where they reside."
                  checked={baseCityEnabled}
                  onChange={(checked) => setValue("base_city_enabled", checked, { shouldDirty: true })}
                />

                <div className={`rounded-xl border p-4 transition-colors ${airportEnabled ? "border-blue-200 bg-blue-50/40" : "border-slate-200 bg-white"}`}>
                  <FormOptionToggle
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

                <FormOptionToggle
                  label="Staff Code"
                  description="Require each client to enter their staff code."
                  checked={staffCodeEnabled}
                  onChange={(checked) => setValue("staff_code_enabled", checked, { shouldDirty: true })}
                />
                <FormOptionToggle
                  label="Meal Preference"
                  description="Require each client to choose Veg, Non Veg, or Jain."
                  checked={mealPreferenceEnabled}
                  onChange={(checked) => setValue("meal_preference_enabled", checked, { shouldDirty: true })}
                />
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                This will generate:
                <div className="mt-2">1. An upload link for clients on phones or browsers</div>
              </div>

              <div className="flex justify-end gap-3 pt-4">
                <Button type="button" variant="secondary" onClick={handleClose}>
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

function FormOptionToggle({
  label,
  description,
  checked,
  onChange,
  borderless = false,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  borderless?: boolean;
}) {
  const containerClassName = borderless
    ? "flex items-start justify-between gap-4"
    : `flex items-start justify-between gap-4 rounded-xl border p-4 transition-colors ${checked ? "border-blue-200 bg-blue-50/40" : "border-slate-200 bg-white"}`;

  return (
    <div className={containerClassName}>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-800">{label}</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={`${checked ? "Disable" : "Enable"} ${label}`}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-7 w-12 shrink-0 overflow-hidden rounded-full border transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${checked ? "border-blue-600 bg-blue-600" : "border-slate-300 bg-slate-200"}`}
      >
        <span className={`pointer-events-none absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm ring-1 ring-slate-900/5 transition-transform duration-200 ${checked ? "translate-x-5" : "translate-x-0"}`} />
      </button>
    </div>
  );
}
