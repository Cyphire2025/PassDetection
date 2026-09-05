"use client";

import { Button, Input } from "@/components/ui";
import { isSupportedIanaTimeZone } from "../utils/trip-timezone";
import { getUploadLinkSettings, getUploadLinkSettingsError, UploadLinkSettings } from "./upload-link-settings";
import type { UploadConfiguration } from "../types/upload-configuration";
import type { CustomUploadDetail, CustomUploadQuestion } from "../api/upload-links.api";
import { TripTimeZoneField } from "./trip-timezone-field";

export interface TripDetailsForm {
  name: string;
  destination: string;
  travel_date: string;
  return_date: string;
  timezone: string;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  meal_preference_enabled: boolean;
  require_selfie: boolean;
  allow_files_from_device: boolean;
  ask_nearest_domestic_airport: boolean;
  relation_with_qualifier_enabled: boolean;
  designation_enabled: boolean;
  agency_dealership_name_enabled: boolean;
  notes: string;
  upload_configuration?: UploadConfiguration;
  custom_questions?: CustomUploadQuestion[];
  custom_details?: CustomUploadDetail[];
}

export function TripDetailsDialog({
  form,
  isLoading,
  onChange,
  onClose,
  onSave,
}: {
  form: TripDetailsForm;
  isLoading: boolean;
  onChange: (form: TripDetailsForm) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const settings = getUploadLinkSettings(form);
  const settingsError = getUploadLinkSettingsError(settings);
  const timezoneError = isSupportedIanaTimeZone(form.timezone)
    ? undefined
    : "Enter a valid IANA timezone, such as Asia/Kolkata";
  const updateField = (key: keyof typeof form, value: string) => {
    onChange({ ...form, [key]: value });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Edit Trip Details</h2>
          <p className="mt-1 text-sm text-slate-500">These details appear in group views, search, filters, and exports.</p>
        </div>
        <div className="grid max-h-[70vh] gap-4 overflow-y-auto p-6 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Group Name</span>
            <Input value={form.name} onChange={(event) => updateField("name", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Destination</span>
            <Input value={form.destination} onChange={(event) => updateField("destination", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Travel/Departure Date</span>
            <Input type="date" value={form.travel_date} onChange={(event) => updateField("travel_date", event.target.value)} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">Return Date</span>
            <Input type="date" value={form.return_date} onChange={(event) => updateField("return_date", event.target.value)} />
          </label>
          <TripTimeZoneField
            value={form.timezone}
            onChange={(event) => updateField("timezone", event.target.value)}
            error={timezoneError}
            required
          />
          <div className="sm:col-span-2">
            <UploadLinkSettings value={settings} onChange={(patch) => onChange({ ...form, ...patch })} disabled={isLoading} error={settingsError} />
          </div>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSave}
            isLoading={isLoading}
            disabled={
              isLoading
              || Boolean(timezoneError)
              || Boolean(settingsError)
              || (form.nearest_international_airport_enabled && form.departure_cities.length === 0)
            }
          >
            Save Details
          </Button>
        </div>
      </div>
    </div>
  );
}
