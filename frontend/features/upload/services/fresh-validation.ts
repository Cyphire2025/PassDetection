import { isUploadFieldRequired } from "@/features/passports/types/upload-configuration";
import type { FreshDraft, FreshPayload } from "../api/fresh-draft.api";
import type { getUploadFlowSettings } from "./configured-upload";
import { configuredReviewError } from "./review-submission-validation";
import { hasMissingRequiredFields, hasValidReviewDates } from "./upload-flow-helpers";

export function freshValidation(settings: ReturnType<typeof getUploadFlowSettings>, payload: FreshPayload, draft: FreshDraft): string | null {
  const documentError = freshDocumentError(settings, payload, draft);
  if (documentError) return documentError;
  const details = payload.current_details;
  if (settings.airportEnabled && isUploadFieldRequired(settings.uploadConfig, "departure_city") && !details.departure_city) return "Select your nearest international airport.";
  if (settings.relationWithQualifierEnabled && isUploadFieldRequired(settings.uploadConfig, "relation_with_qualifier") && !payload.collection?.qualifier_selection_token) return "Choose your relationship with the qualifier.";
  if (payload.collection?.submission_mode === "family" && (!payload.collection.family_relation || !payload.collection.family_gender)) return "Select this family member’s relationship and gender.";
  return configuredReviewError(settings, configuredFields(payload));
}

function freshDocumentError(settings: ReturnType<typeof getUploadFlowSettings>, payload: FreshPayload, draft: FreshDraft): string | null {
  const pages = payload.collection?.acquisition_mode === "camera" ? ["front", "back"] : settings.uploadConfig.passport_upload_pages;
  if (settings.passportRequired && pages.some((side) => !draft.documents.some((document) => document.side === side && document.state === "ready"))) return "Add every requested passport page before submitting.";
  if (settings.selfieRequired && !draft.documents.some((document) => document.side === "photo" && document.state === "ready")) return "Add your traveller photo before submitting.";
  const hasPassport = draft.documents.some((document) => document.side === "front");
  if (hasPassport && draft.extraction_status !== "succeeded") return "Wait for the passport check to finish. If it failed, replace the details page with a clear image.";
  if (hasPassport && hasMissingRequiredFields(payload.passport_fields)) return "Complete the required passport details.";
  if (hasPassport && !hasValidReviewDates(payload.passport_fields)) return "Check your passport dates before submitting.";
  if (!hasPassport && (payload.current_details.client_name ?? "").trim().length < 2) return "Enter your full name.";
  return null;
}
function configuredFields(payload: FreshPayload) {
  const details = payload.current_details;
  return { baseCity: details.base_city ?? "", nearestDomesticAirport: details.nearest_domestic_airport ?? "", staffCode: details.staff_code ?? "", agentEmployeeCode: details.agent_employee_code ?? "", designation: details.designation ?? "", agencyDealershipName: details.agency_dealership_name ?? "", mealPreference: details.meal_preference ?? "", customAnswers: payload.custom_answers, customDetailAnswers: payload.custom_detail_answers };
}
