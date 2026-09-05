"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { CustomUploadDetail, CustomUploadQuestion } from "../api/upload-links.api";
import { customDetailSchema, customQuestionSchema, uploadConfigurationSchema } from "../schemas/upload-link.schema";
import {
  DEFAULT_UPLOAD_CONFIGURATION,
  PASSPORT_UPLOAD_PAGES,
  isUploadFieldRequired,
  type RequiredUploadField,
  type UploadConfiguration,
} from "../types/upload-configuration";
import { normalizeCities, normalizeCity } from "../utils/passport-group-trip";
import { GroupOptionToggle } from "./group-option-toggle";
import { CustomQuestionBuilder } from "./custom-question-builder";
import { CustomDetailBuilder } from "./custom-detail-builder";

export interface UploadLinkSettingsValue {
  require_selfie: boolean;
  allow_files_from_device: boolean;
  base_city_enabled: boolean;
  ask_nearest_domestic_airport: boolean;
  nearest_international_airport_enabled: boolean;
  departure_cities: string[];
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  agency_dealership_name_enabled: boolean;
  designation_enabled: boolean;
  meal_preference_enabled: boolean;
  relation_with_qualifier_enabled: boolean;
  upload_configuration: UploadConfiguration;
  custom_questions: CustomUploadQuestion[];
  custom_details: CustomUploadDetail[];
}

export function getUploadLinkSettings(value: Omit<Partial<UploadLinkSettingsValue>, "upload_configuration"> & {
  upload_configuration?: UploadConfiguration | null;
}): UploadLinkSettingsValue {
  const configuration = value.upload_configuration;
  return {
    require_selfie: value.require_selfie ?? false,
    allow_files_from_device: value.allow_files_from_device ?? true,
    base_city_enabled: value.base_city_enabled ?? false,
    ask_nearest_domestic_airport: value.ask_nearest_domestic_airport ?? false,
    nearest_international_airport_enabled: Boolean(value.nearest_international_airport_enabled)
      || (configuration == null && (value.departure_cities?.length ?? 0) > 0),
    departure_cities: [...(value.departure_cities ?? [])],
    staff_code_enabled: value.staff_code_enabled ?? false,
    agent_employee_code_enabled: value.agent_employee_code_enabled ?? false,
    agency_dealership_name_enabled: value.agency_dealership_name_enabled ?? false,
    designation_enabled: value.designation_enabled ?? false,
    meal_preference_enabled: value.meal_preference_enabled ?? false,
    relation_with_qualifier_enabled: value.relation_with_qualifier_enabled ?? false,
    upload_configuration: {
      ...DEFAULT_UPLOAD_CONFIGURATION,
      ...configuration,
      passport_upload_pages: [...(configuration?.passport_upload_pages ?? DEFAULT_UPLOAD_CONFIGURATION.passport_upload_pages)],
      required_fields: { ...configuration?.required_fields },
    },
    custom_questions: (value.custom_questions ?? []).map((question) => ({ ...question, required: question.required ?? true })),
    custom_details: (value.custom_details ?? []).map((detail) => ({ ...detail, required: detail.required ?? true })),
  };
}

export function getUploadLinkSettingsError(value: UploadLinkSettingsValue): string | undefined {
  const configuration = value.upload_configuration;
  const parsedConfiguration = uploadConfigurationSchema.safeParse(configuration);
  if (!parsedConfiguration.success) return parsedConfiguration.error.issues[0]?.message;
  if (value.require_selfie && !configuration.visa_photo_live_capture && !configuration.visa_photo_upload) {
    return "Enable at least one method for Visa Photo.";
  }
  if (configuration.passport_enabled && !configuration.passport_live_scan && !value.allow_files_from_device) {
    return "Enable at least one method for Passport.";
  }
  if (configuration.passport_enabled && value.allow_files_from_device && configuration.passport_upload_pages.length === 0) {
    return "Select at least one passport page to upload.";
  }
  if (value.nearest_international_airport_enabled && value.departure_cities.length === 0) {
    return "Add at least one nearest international airport.";
  }
  for (const question of value.custom_questions) {
    const parsed = customQuestionSchema.safeParse(question);
    if (!parsed.success) return parsed.error.issues[0]?.message;
  }
  for (const detail of value.custom_details) {
    const parsed = customDetailSchema.safeParse(detail);
    if (!parsed.success) return parsed.error.issues[0]?.message;
  }
  if (new Set(value.custom_questions.map((question) => question.label.trim().toLocaleLowerCase())).size !== value.custom_questions.length) {
    return "Custom question names must be unique.";
  }
  if (new Set(value.custom_details.map((detail) => detail.label.trim().toLocaleLowerCase())).size !== value.custom_details.length) {
    return "Custom detail names must be unique.";
  }
}

export function UploadLinkSettings({
  value,
  onChange,
  disabled = false,
  error,
}: {
  value: UploadLinkSettingsValue;
  onChange: (patch: Partial<UploadLinkSettingsValue>) => void;
  disabled?: boolean;
  error?: string;
}) {
  const [cityInput, setCityInput] = useState("");
  const configuration = value.upload_configuration;
  const updateConfiguration = (patch: Partial<UploadConfiguration>) => {
    onChange({ upload_configuration: { ...configuration, ...patch } });
  };
  const requiredControl = (field: RequiredUploadField) => ({
    required: isUploadFieldRequired(configuration, field),
    onRequiredChange: (required: boolean) => updateConfiguration({
      required_fields: { ...configuration.required_fields, [field]: required },
    }),
  });
  const addCity = () => {
    const city = normalizeCity(cityInput);
    if (!city || value.departure_cities.length >= 50) return;
    onChange({ departure_cities: normalizeCities([...value.departure_cities, city]) });
    setCityInput("");
  };

  return (
    <div className="space-y-5">
      <SettingsSection title="Visa Photo" number="01">
        <GroupOptionToggle
          label="Visa Photo"
          description="Collect a visa photograph against a plain white or off-white background."
          checked={value.require_selfie}
          onChange={(require_selfie) => onChange({ require_selfie })}
          required={configuration.visa_photo_required}
          onRequiredChange={(visa_photo_required) => updateConfiguration({ visa_photo_required })}
          disabled={disabled}
          borderless
        />
        {value.require_selfie && (
          <div className="space-y-3 border-t border-slate-200 pt-4">
            <GroupOptionToggle label="Live Photo Capture" description="Show the camera so travellers can take a new photograph."
              checked={configuration.visa_photo_live_capture} onChange={(visa_photo_live_capture) => updateConfiguration({ visa_photo_live_capture })} disabled={disabled} />
            <GroupOptionToggle label="Photo Upload" description="Let travellers upload a photograph from their device."
              checked={configuration.visa_photo_upload} onChange={(visa_photo_upload) => updateConfiguration({ visa_photo_upload })} disabled={disabled} />
            <p className="text-xs leading-5 text-slate-500">Travellers can use either enabled method. If compulsory, one visa photograph is required.</p>
          </div>
        )}
      </SettingsSection>

      <SettingsSection title="Passport" number="02">
        <GroupOptionToggle
          label="Passport"
          description="Collect passport pages using the live scanner or document upload."
          checked={configuration.passport_enabled}
          onChange={(passport_enabled) => updateConfiguration({ passport_enabled })}
          required={configuration.passport_required}
          onRequiredChange={(passport_required) => updateConfiguration({ passport_required })}
          disabled={disabled}
          borderless
        />
        {configuration.passport_enabled && (
          <div className="space-y-3 border-t border-slate-200 pt-4">
            <GroupOptionToggle label="Live Passport Scan" description="Scan the personal details and address details pages with the existing live scanner."
              checked={configuration.passport_live_scan} onChange={(passport_live_scan) => updateConfiguration({ passport_live_scan })} disabled={disabled} />
            <GroupOptionToggle label="Passport Document Upload" description="Let travellers upload scanned passport pages. Each file must be 2 MB or smaller."
              checked={value.allow_files_from_device} onChange={(allow_files_from_device) => onChange({ allow_files_from_device })} disabled={disabled} />
            {value.allow_files_from_device && (
              <details className="rounded-xl border border-slate-200 bg-white">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                  <span>Pages to request <span className="ml-1 font-normal text-slate-500">({configuration.passport_upload_pages.length} selected)</span></span>
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                </summary>
                <div className="space-y-3 border-t border-slate-100 p-4">
                  {PASSPORT_UPLOAD_PAGES.map((page) => (
                    <label key={page.id} className="flex cursor-pointer items-start gap-3 text-sm text-slate-800">
                      <input type="checkbox" checked={configuration.passport_upload_pages.includes(page.id)} disabled={disabled}
                        onChange={(event) => updateConfiguration({ passport_upload_pages: PASSPORT_UPLOAD_PAGES.filter((option) => option.id === page.id ? event.target.checked : configuration.passport_upload_pages.includes(option.id)).map((option) => option.id) })}
                        className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600" />
                      <span><span className="font-medium">{page.label}</span><span className="mt-0.5 block text-xs leading-5 text-slate-500">{page.description}</span></span>
                    </label>
                  ))}
                </div>
              </details>
            )}
            <p className="text-xs leading-5 text-slate-500">Travellers can use either enabled method. Uploads appear in the page order shown above; live scanning continues to collect the two details pages.</p>
          </div>
        )}
      </SettingsSection>

      <SettingsSection title="Travel Preferences" number="03">
        <GroupOptionToggle label="Base City" description="Ask for the traveller’s city of residence."
          checked={value.base_city_enabled} onChange={(base_city_enabled) => onChange({ base_city_enabled })} disabled={disabled} {...requiredControl("base_city")} />
        <GroupOptionToggle label="Nearest Domestic Airport" description="Ask for the traveller’s nearest domestic airport."
          checked={value.ask_nearest_domestic_airport} onChange={(ask_nearest_domestic_airport) => onChange({ ask_nearest_domestic_airport })} disabled={disabled} {...requiredControl("nearest_domestic_airport")} />
        <GroupOptionToggle label="Nearest International Airport" description="Let travellers choose from your list of international airports."
          checked={value.nearest_international_airport_enabled} onChange={(nearest_international_airport_enabled) => onChange({ nearest_international_airport_enabled, upload_configuration: configuration })} disabled={disabled} {...requiredControl("departure_city")} />
        {value.nearest_international_airport_enabled && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-end gap-2">
              <Input label="International airport options" placeholder="e.g. Delhi, Chennai, Mumbai" value={cityInput} disabled={disabled} maxLength={120}
                onChange={(event) => setCityInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCity(); } }} />
              <Button type="button" variant="secondary" onClick={addCity} disabled={disabled || !cityInput.trim() || value.departure_cities.length >= 50}>Add</Button>
            </div>
            {value.departure_cities.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {value.departure_cities.map((city) => (
                  <button key={city} type="button" disabled={disabled} aria-label={`Remove ${city}`}
                    onClick={() => onChange({ departure_cities: value.departure_cities.filter((item) => item !== city) })}
                    className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800 hover:bg-blue-100 disabled:opacity-50">
                    {city}<X className="h-3 w-3" aria-hidden="true" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </SettingsSection>

      <SettingsSection title="Professional Details" number="04">
        <GroupOptionToggle label="Agent/Employee Code" description="Collect a code using a field name that suits this group."
          checked={value.agent_employee_code_enabled} onChange={(agent_employee_code_enabled) => onChange({ agent_employee_code_enabled })} disabled={disabled} {...requiredControl("agent_employee_code")} />
        {value.agent_employee_code_enabled && (
          <Input label="Code field label" value={configuration.agent_employee_code_label} maxLength={100} disabled={disabled}
            placeholder="e.g. Producer Code" onChange={(event) => updateConfiguration({ agent_employee_code_label: event.target.value })} />
        )}
        <GroupOptionToggle label="Staff Code" description="Ask for the traveller’s staff code."
          checked={value.staff_code_enabled} onChange={(staff_code_enabled) => onChange({ staff_code_enabled })} disabled={disabled} {...requiredControl("staff_code")} />
        <GroupOptionToggle label="Agency/Dealership Name" description="Collect the organisation name using a label that suits this group."
          checked={value.agency_dealership_name_enabled} onChange={(agency_dealership_name_enabled) => onChange({ agency_dealership_name_enabled })} disabled={disabled} {...requiredControl("agency_dealership_name")} />
        {value.agency_dealership_name_enabled && (
          <Input label="Organisation field label" value={configuration.agency_dealership_name_label} maxLength={100} disabled={disabled}
            placeholder="e.g. Company Name" onChange={(event) => updateConfiguration({ agency_dealership_name_label: event.target.value })} />
        )}
        <GroupOptionToggle label="Designation" description="Ask for the traveller’s job title or designation."
          checked={value.designation_enabled} onChange={(designation_enabled) => onChange({ designation_enabled })} disabled={disabled} {...requiredControl("designation")} />
      </SettingsSection>

      <SettingsSection title="Miscellaneous" number="05">
        <GroupOptionToggle label="Meal Preference" description="Let travellers select Vegetarian, Non-Vegetarian or Jain."
          checked={value.meal_preference_enabled} onChange={(meal_preference_enabled) => onChange({ meal_preference_enabled })} disabled={disabled} {...requiredControl("meal_preference")} />
        <GroupOptionToggle label="Relation with Qualifier" description="Ask whether the traveller is the qualifier or an approved family member."
          checked={value.relation_with_qualifier_enabled} onChange={(relation_with_qualifier_enabled) => onChange({ relation_with_qualifier_enabled })} disabled={disabled} {...requiredControl("relation_with_qualifier")} />
        <CustomQuestionBuilder questions={value.custom_questions} onChange={(custom_questions) => onChange({ custom_questions })} disabled={disabled} />
        <CustomDetailBuilder details={value.custom_details} onChange={(custom_details) => onChange({ custom_details })} disabled={disabled} />
      </SettingsSection>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    </div>
  );
}

function SettingsSection({ title, number, children }: { title: string; number: string; children: ReactNode }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50/40">
      <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <span className="text-xs font-medium tabular-nums text-slate-400" aria-hidden="true">{number}</span>
        <h3 id={titleId} className="text-sm font-semibold text-slate-900">{title}</h3>
      </div>
      <div className="space-y-3 p-4">{children}</div>
    </section>
  );
}
