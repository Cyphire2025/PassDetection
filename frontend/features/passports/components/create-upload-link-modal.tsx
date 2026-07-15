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
      notes: "",
    },
  });
  const departureCities = useWatch({ control, name: "departure_cities" }) ?? [];

  if (!isOpen) return null;

  const onSubmit = async (data: CreateUploadLinkFormData) => {
    try {
      const result = await createUploadLink({
        ...data,
        destination: data.destination || null,
        travel_date: data.travel_date || null,
        return_date: data.return_date || null,
        departure_cities: normalizeCities(data.departure_cities ?? []),
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

              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">Departure Cities</label>
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
                <p className="text-xs text-slate-500">
                  Clients will choose one of these cities while submitting their passport.
                </p>
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
