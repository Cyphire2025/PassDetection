"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { Button, Input } from "@/components/ui";
import { normalizeCity, normalizeCities } from "../utils/passport-group-trip";
import { GroupOptionToggle } from "./group-option-toggle";

export function TripDetailsDialog({
  form,
  isLoading,
  onChange,
  onClose,
  onSave,
}: {
  form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
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
  };
  isLoading: boolean;
  onChange: (form: {
    name: string;
    destination: string;
    travel_date: string;
    return_date: string;
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
  }) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const [cityInput, setCityInput] = useState("");
  const updateField = (key: keyof typeof form, value: string) => {
    onChange({ ...form, [key]: value });
  };
  const addCity = () => {
    const nextCity = normalizeCity(cityInput);
    if (!nextCity) return;
    onChange({ ...form, departure_cities: normalizeCities([...form.departure_cities, nextCity]) });
    setCityInput("");
  };
  const removeCity = (city: string) => {
    onChange({ ...form, departure_cities: form.departure_cities.filter((item) => item !== city) });
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
          <GroupOptionToggle
            label="Visa Photo Upload"
            description="Require a Visa Photo against a plain white or off-white wall."
            checked={form.require_selfie}
            onChange={(checked) => onChange({ ...form, require_selfie: checked })}
          />
          <GroupOptionToggle
            label="Allow files from device"
            description="Let travellers choose existing passport images as well as use the live scanner."
            checked={form.allow_files_from_device}
            onChange={(checked) => onChange({ ...form, allow_files_from_device: checked })}
          />
          <GroupOptionToggle
            label="Ask for nearest domestic airport"
            description="Require each traveller to enter their nearest domestic airport."
            checked={form.ask_nearest_domestic_airport}
            onChange={(checked) => onChange({ ...form, ask_nearest_domestic_airport: checked })}
          />
          <GroupOptionToggle
            label="Relation with Qualifier"
            description="Require Self or one approved family relationship before a single-passenger upload."
            checked={form.relation_with_qualifier_enabled}
            onChange={(checked) => onChange({
              ...form,
              relation_with_qualifier_enabled: checked,
            })}
          />
          <GroupOptionToggle
            label="Base City"
            description="Require each client to enter their city of residence."
            checked={form.base_city_enabled}
            onChange={(checked) => onChange({ ...form, base_city_enabled: checked })}
          />
          <GroupOptionToggle
            label="Designation"
            description="Require each traveller to type their designation."
            checked={form.designation_enabled}
            onChange={(checked) => onChange({ ...form, designation_enabled: checked })}
          />
          <GroupOptionToggle
            label="Agency/Dealership Name"
            description="Require each traveller to type their agency or dealership name."
            checked={form.agency_dealership_name_enabled}
            onChange={(checked) => onChange({
              ...form,
              agency_dealership_name_enabled: checked,
            })}
          />
          <GroupOptionToggle
            label="Staff Code"
            description="Require each client to enter a staff code."
            checked={form.staff_code_enabled}
            onChange={(checked) => onChange({ ...form, staff_code_enabled: checked })}
          />
          <GroupOptionToggle
            label="Agent/Employee Code"
            description="Require each client to select Agent or Employee and enter a numeric code."
            checked={form.agent_employee_code_enabled}
            onChange={(checked) => onChange({ ...form, agent_employee_code_enabled: checked })}
          />
          <div className="space-y-3 rounded-xl border border-slate-200 p-4 sm:col-span-2">
            <GroupOptionToggle
              label="Nearest International Airport"
              description="Require clients to select one configured airport."
              checked={form.nearest_international_airport_enabled}
              onChange={(checked) => onChange({
                ...form,
                nearest_international_airport_enabled: checked,
                departure_cities: checked ? form.departure_cities : [],
              })}
              borderless
            />
            {form.nearest_international_airport_enabled && (
              <div className="space-y-2 border-t border-slate-100 pt-3">
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
                  <Button type="button" variant="secondary" onClick={addCity}>Add</Button>
                </div>
                {form.departure_cities.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {form.departure_cities.map((city) => (
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
                {form.departure_cities.length === 0 && <p className="text-xs text-amber-700">Add at least one airport.</p>}
              </div>
            )}
          </div>
          <GroupOptionToggle
            label="Meal Preference"
            description="Require Veg, Non Veg, or Jain selection."
            checked={form.meal_preference_enabled}
            onChange={(checked) => onChange({ ...form, meal_preference_enabled: checked })}
          />
          <label className="space-y-2 sm:col-span-2">
            <span className="text-sm font-medium text-slate-700">Notes</span>
            <textarea
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              rows={4}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSave}
            isLoading={isLoading}
            disabled={isLoading || (form.nearest_international_airport_enabled && form.departure_cities.length === 0)}
          >
            Save Details
          </Button>
        </div>
      </div>
    </div>
  );
}
