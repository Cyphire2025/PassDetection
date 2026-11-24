import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";
import { getUploadLinkSettings } from "./upload-link-settings-model";

export function createUploadLinkDefaults() {
  return {
    company_id: "",
    import_only: false,
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
    matching_fields_by_broadcast: {},
    upload_configuration: getUploadLinkSettings({}).upload_configuration,
  };
}
