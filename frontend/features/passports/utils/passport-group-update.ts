import type { TripDetailsForm } from "../types/passport-trip-details";
import { normalizeCities } from "./passport-group-trip";

export function tripDetailsUpdate(groupId: string, form: TripDetailsForm, fallbackName: string) {
  return {
    id: groupId,
    name: form.name.trim() || fallbackName,
    destination: form.destination || null,
    travel_date: form.travel_date || null,
    return_date: form.return_date || null,
    timezone: form.timezone.trim(),
    departure_cities: form.nearest_international_airport_enabled
      ? normalizeCities(form.departure_cities)
      : [],
    base_city_enabled: form.base_city_enabled,
    nearest_international_airport_enabled:
      form.nearest_international_airport_enabled,
    staff_code_enabled: form.staff_code_enabled,
    agent_employee_code_enabled:
      form.agent_employee_code_enabled,
    meal_preference_enabled: form.meal_preference_enabled,
    upload_configuration: form.upload_configuration,
    custom_questions: form.custom_questions,
    custom_details: form.custom_details,
    require_selfie: form.require_selfie,
    allow_files_from_device: form.allow_files_from_device,
    ask_nearest_domestic_airport:
      form.ask_nearest_domestic_airport,
    relation_with_qualifier_enabled:
      form.relation_with_qualifier_enabled,
    designation_enabled: form.designation_enabled,
    agency_dealership_name_enabled:
      form.agency_dealership_name_enabled,
    notes: form.notes || null,
  };
}
