import { isUploadFieldRequired, type RequiredUploadField } from "@/features/passports/types/upload-configuration";
import type { getUploadFlowSettings } from "./configured-upload";

export interface ConfiguredReviewDraft {
  baseCity: string; nearestDomesticAirport: string; staffCode: string;
  agentEmployeeCode: string; designation: string; agencyDealershipName: string;
  mealPreference: string; customAnswers: Record<string, string>; customDetailAnswers: Record<string, string>;
}

/** All current private drafts obey the same configured fields and labels. */
export function configuredReviewError(settings: ReturnType<typeof getUploadFlowSettings>, draft: ConfiguredReviewDraft): string | null {
  const { uploadConfig } = settings;
  const checks: Array<{ enabled: boolean; field: RequiredUploadField; value: string; message: string }> = [
    { enabled: settings.baseCityEnabled, field: "base_city", value: draft.baseCity.trim(), message: "Please enter your base city before submitting." },
    { enabled: settings.askNearestDomesticAirport, field: "nearest_domestic_airport", value: draft.nearestDomesticAirport.trim(), message: "Please enter your nearest domestic airport before submitting." },
    { enabled: settings.staffCodeEnabled, field: "staff_code", value: draft.staffCode.trim(), message: "Please enter your staff code before submitting." },
    { enabled: settings.agentEmployeeCodeEnabled, field: "agent_employee_code", value: draft.agentEmployeeCode.trim(), message: `Please enter your ${uploadConfig.agent_employee_code_label.toLowerCase()}.` },
    { enabled: settings.designationEnabled, field: "designation", value: draft.designation.trim(), message: "Please enter your designation before submitting." },
    { enabled: settings.agencyDealershipNameEnabled, field: "agency_dealership_name", value: draft.agencyDealershipName.trim(), message: `Please enter your ${uploadConfig.agency_dealership_name_label.toLowerCase()}.` },
    { enabled: settings.mealPreferenceEnabled, field: "meal_preference", value: draft.mealPreference, message: "Please select a meal preference before submitting." },
  ];
  const missing = checks.find((check) => check.enabled && isUploadFieldRequired(uploadConfig, check.field) && !check.value);
  if (missing) return missing.message;
  if (settings.enabledCustomQuestions.some((question) => question.required !== false && !draft.customAnswers[question.id])) return "Please answer every custom question before submitting.";
  if (settings.enabledCustomDetails.some((detail) => detail.required !== false && !draft.customDetailAnswers[detail.id]?.trim())) return "Please complete every custom detail before submitting.";
  return null;
}
