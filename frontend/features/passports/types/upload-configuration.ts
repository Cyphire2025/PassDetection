export type PassportUploadPage = "cover" | "back_cover" | "front" | "back";
export type RequiredUploadField = "base_city" | "nearest_domestic_airport" | "departure_city"
  | "staff_code" | "agent_employee_code" | "designation" | "agency_dealership_name"
  | "meal_preference" | "relation_with_qualifier";

export interface UploadConfiguration {
  passport_enabled: boolean;
  passport_required: boolean;
  passport_live_scan: boolean;
  passport_upload_pages: PassportUploadPage[];
  visa_photo_required: boolean;
  visa_photo_live_capture: boolean;
  visa_photo_upload: boolean;
  required_fields: Partial<Record<RequiredUploadField, boolean>>;
  agent_employee_code_label: string;
  agency_dealership_name_label: string;
}

export const DEFAULT_UPLOAD_CONFIGURATION: UploadConfiguration = {
  passport_enabled: true,
  passport_required: true,
  passport_live_scan: true,
  passport_upload_pages: ["front", "back"],
  visa_photo_required: true,
  visa_photo_live_capture: true,
  visa_photo_upload: true,
  required_fields: {},
  agent_employee_code_label: "Agent/Employee Code",
  agency_dealership_name_label: "Agency/Dealership Name",
};

export const PASSPORT_UPLOAD_PAGES: { id: PassportUploadPage; label: string; description: string }[] = [
  { id: "cover", label: "Passport Front Cover", description: "The outside front cover of the closed passport booklet." },
  { id: "back_cover", label: "Passport Back Cover", description: "The outside back cover of the closed passport booklet." },
  { id: "front", label: "Personal Details Page", description: "The main page with your photograph, passport number and machine-readable text." },
  { id: "back", label: "Address Details Page", description: "The page with your address, parents’ names and other particulars, where applicable." },
];

export const MAX_PASSPORT_UPLOAD_BYTES = 2 * 1024 * 1024;
export const isUploadFieldRequired = (config: UploadConfiguration, field: RequiredUploadField) => config.required_fields[field] ?? true;
