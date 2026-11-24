import type { CustomUploadDetail, CustomUploadQuestion } from "../api/upload-links.api";
import { customDetailSchema, customQuestionSchema, uploadConfigurationSchema } from "../schemas/upload-link.schema";
import { DEFAULT_UPLOAD_CONFIGURATION, type UploadConfiguration } from "../types/upload-configuration";

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
  upload_configuration?: Partial<UploadConfiguration> | null;
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
      instruction_languages: [...(configuration?.instruction_languages ?? [])],
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
  if (configuration.passport_ecr_enabled && value.allow_files_from_device && !configuration.passport_upload_pages.includes("back")) {
    return "Include the Address Details Page for the ECR check.";
  }
  if (value.relation_with_qualifier_enabled && !configuration.qualifier_relation_list_enabled && !configuration.qualifier_relation_other_enabled) {
    return "Enable at least one option for Relation with Qualifier.";
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
