import {
  DEFAULT_UPLOAD_CONFIGURATION,
  MAX_PASSPORT_UPLOAD_BYTES,
  PASSPORT_UPLOAD_PAGES,
  type PassportUploadPage,
  type UploadConfiguration,
} from "@/features/passports/types/upload-configuration";
import type { PassportDocumentBundle } from "../components/upload-flow.types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";

export function resolveUploadConfiguration(value?: Partial<UploadConfiguration> | null): UploadConfiguration {
  return { ...DEFAULT_UPLOAD_CONFIGURATION, ...value, required_fields: value?.required_fields ?? {} };
}

/** Keeps legacy link defaults and explicit current settings in one boundary. */
export function getUploadFlowSettings(group?: UploadLinkResponse) {
  const uploadConfig = resolveUploadConfiguration(group?.upload_configuration);
  const airportEnabled = group?.upload_configuration
    ? Boolean(group.nearest_international_airport_enabled)
    : Boolean(group?.nearest_international_airport_enabled || group?.departure_cities?.length);
  const selfieEnabled = group?.require_selfie ?? false;
  return {
    uploadConfig,
    groupId: group?.id,
    airportEnabled,
    departureCities: airportEnabled ? group?.departure_cities ?? [] : [],
    baseCityEnabled: group?.base_city_enabled ?? false,
    staffCodeEnabled: group?.staff_code_enabled ?? false,
    agentEmployeeCodeEnabled: group?.agent_employee_code_enabled ?? false,
    designationEnabled: group?.designation_enabled ?? false,
    agencyDealershipNameEnabled: group?.agency_dealership_name_enabled ?? false,
    mealPreferenceEnabled: group?.meal_preference_enabled ?? false,
    selfieEnabled,
    selfieRequired: selfieEnabled && uploadConfig.visa_photo_required,
    passportEnabled: uploadConfig.passport_enabled,
    passportRequired: uploadConfig.passport_enabled && uploadConfig.passport_required,
    allowFilesFromDevice: group?.allow_files_from_device ?? true,
    askNearestDomesticAirport: group?.ask_nearest_domestic_airport ?? false,
    relationWithQualifierEnabled: group?.relation_with_qualifier_enabled ?? false,
    enabledCustomQuestions: (group?.custom_questions ?? []).filter((question) => question.enabled),
    enabledCustomDetails: (group?.custom_details ?? []).filter((detail) => detail.enabled),
  };
}

export function passportUploadFileError(file: File): string | null {
  if (file.size > MAX_PASSPORT_UPLOAD_BYTES) return "Each passport image must be 2 MB or smaller. Please choose a smaller file.";
  if (!file.size) return "This file is empty. Please choose a passport image.";
  if (!/^image\/(jpeg|png|webp|heic|heif|avif|bmp|tiff)$/i.test(file.type)
    && !/\.(jpe?g|png|webp|heic|heif|avif|bmp|tiff?)$/i.test(file.name)) {
    return "Choose a passport image in JPG, PNG, WebP, HEIC, HEIF, AVIF, BMP or TIFF format.";
  }
  return null;
}

export function passportBundleError(
  bundle: PassportDocumentBundle,
  config: UploadConfiguration,
  mode: "camera" | "file",
): string | null {
  const pages: PassportUploadPage[] = mode === "camera" ? ["front", "back"] : config.passport_upload_pages;
  const missing = PASSPORT_UPLOAD_PAGES.find((page) => pages.includes(page.id) && !bundle[page.id]);
  if (missing) return `Please add the ${missing.label.toLowerCase()} before continuing.`;
  if (mode === "file") {
    for (const page of pages) {
      const file = bundle[page];
      if (file) {
        const error = passportUploadFileError(file);
        if (error) return error;
      }
    }
  }
  return null;
}
