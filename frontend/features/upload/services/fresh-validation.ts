import { isUploadFieldRequired } from "@/features/passports/types/upload-configuration";
import type { FreshDraft, FreshPayload } from "../api/fresh-draft.api";
import type { getUploadFlowSettings } from "./configured-upload";
import { configuredReviewError } from "./review-submission-validation";
import { freshDocumentError } from "./fresh-document-validation";

export function freshValidation(settings: ReturnType<typeof getUploadFlowSettings>, payload: FreshPayload, draft: FreshDraft): string | null {
  const documentError = freshDocumentError(settings, payload, draft);
  if (documentError) return documentError;
  const details = payload.current_details;
  if (settings.airportEnabled && isUploadFieldRequired(settings.uploadConfig, "departure_city") && !details.departure_city) return "Select your nearest international airport.";
  if (settings.relationWithQualifierEnabled && isUploadFieldRequired(settings.uploadConfig, "relation_with_qualifier") && !payload.collection?.qualifier_selection_token) return "Choose your relationship with the qualifier.";
  if (payload.collection?.submission_mode === "family" && (!payload.collection.family_relation || !payload.collection.family_gender)) return "Select this family member’s relationship and gender.";
  return configuredReviewError(settings, configuredFields(payload));
}

function configuredFields(payload: FreshPayload) {
  const details = payload.current_details;
  return { baseCity: details.base_city ?? "", nearestDomesticAirport: details.nearest_domestic_airport ?? "", staffCode: details.staff_code ?? "", agentEmployeeCode: details.agent_employee_code ?? "", designation: details.designation ?? "", agencyDealershipName: details.agency_dealership_name ?? "", mealPreference: details.meal_preference ?? "", customAnswers: payload.custom_answers, customDetailAnswers: payload.custom_detail_answers };
}
