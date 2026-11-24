import type { UploadConfiguration } from "./upload-configuration";
import type { CustomUploadDetail, CustomUploadQuestion } from "../api/upload-links.api";

export interface TripDetailsForm {
  import_only?: boolean;
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
