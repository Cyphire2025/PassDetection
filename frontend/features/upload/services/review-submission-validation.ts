import { isUploadFieldRequired, type RequiredUploadField } from "@/features/passports/types/upload-configuration";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import type { PassportSubmission } from "@/types/passport.types";
import type { FamilyMember } from "../components/upload-flow.types";
import type { getUploadFlowSettings } from "./configured-upload";
import { passportDocumentVerificationGate } from "./passport-document-verification";
import { hasMissingRequiredFields, hasValidReviewDates } from "./upload-flow-helpers";

export type SingleReviewDraft = {
  clientName: string; clientEmail: string; clientPhone: string; reviewFields: Record<string, string>;
  departureCity: string; baseCity: string; nearestDomesticAirport: string; staffCode: string;
  agentEmployeeCode: string; designation: string; agencyDealershipName: string; mealPreference: string;
  customAnswers: Record<string, string>; customDetailAnswers: Record<string, string>;
};
type ReviewPolicy = {
  settings: ReturnType<typeof getUploadFlowSettings>; draft: SingleReviewDraft;
  canReviewSubmission: (saved: PassportSubmission) => boolean;
  requiresPassportReview: (saved: PassportSubmission) => boolean;
};

export function validateSingleReview({ submission, settings, draft, canReviewSubmission, requiresPassportReview }: ReviewPolicy & { submission: PassportSubmission }): string | null {
  const { clientName, clientPhone, reviewFields, departureCity } = draft;
  const { airportEnabled, uploadConfig } = settings;
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  if (clientPhone.trim() && !normalizePhoneNumber(clientPhone)) {
    return PHONE_FORMAT_HELP;
  }
  const verificationGate = passportDocumentVerificationGate(submission);
  if (!canReviewSubmission(submission)) {
    return verificationGate.message;
  }
  if (!requiresPassportReview(submission) && clientName.trim().length < 2) {
    return "Please enter your full name before submitting.";
  }
  if (requiresPassportReview(submission) && hasMissingRequiredFields(reviewFields)) {
    return "Please fill all required passport fields before submitting.";
  }
  if (requiresPassportReview(submission) && !hasValidReviewDates(reviewFields)) {
    return "Enter valid passport dates in DD/MM/YYYY format. Check that birth, issue, and expiry are chronological and no entered birth or issue date is in the future.";
  }
  if (airportEnabled && requiredField("departure_city") && !departureCity) {
    return "Please select your nearest international airport before submitting.";
  }
  return configuredReviewError(settings, draft);
}

export function validateFamilyReview({ familyMembers, settings, draft, canReviewSubmission, requiresPassportReview }: ReviewPolicy & { familyMembers: FamilyMember[] }): string | null {
  const { departureCity } = draft;
  const { airportEnabled, uploadConfig } = settings;
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  const headEmail = familyMembers[0]?.email ?? "";
  const headPhone = familyMembers[0]?.phone ?? "";
  if ((headPhone.trim() && !normalizePhoneNumber(headPhone))
    || familyMembers.some((member) => member.phone.trim() && !normalizePhoneNumber(member.phone))) {
    return PHONE_FORMAT_HELP;
  }
  const blockedVerification = familyMembers.find((member) => (
    member.submission !== null
    && !canReviewSubmission(member.submission)
  ));
  if (blockedVerification?.submission) {
    return `${blockedVerification.name || "A family member"}: ${passportDocumentVerificationGate(blockedVerification.submission).message
      }`;
  }
  if (airportEnabled && requiredField("departure_city") && !departureCity) {
    return "Please select the family nearest international airport before submitting.";
  }
  if (!headEmail.trim() || !headPhone.trim()) {
    return "Head of family email and phone number are required.";
  }
  const missingUpload = familyMembers.find((member) => !member.submission);
  if (missingUpload) {
    return `Upload passport for ${missingUpload.name || "every family member"} before submitting.`;
  }
  const invalidReview = familyMembers.find((member) => (
    member.submission && requiresPassportReview(member.submission) && (hasMissingRequiredFields(member.reviewFields) || !hasValidReviewDates(member.reviewFields))
  ));
  if (invalidReview) {
    return `Fill all passport fields for ${invalidReview.name}.`;
  }
  const missingConfiguredField = familyMembers.find((member) => configuredReviewError(settings, member));
  if (missingConfiguredField) {
    return `Complete the required group fields for ${missingConfiguredField.name}.`;
  }

  return null;
}

/** Single and family review obey the same required-field policy and labels. */
export function configuredReviewError(settings: ReturnType<typeof getUploadFlowSettings>, draft: Pick<SingleReviewDraft,
  "baseCity" | "nearestDomesticAirport" | "staffCode" | "agentEmployeeCode" | "designation" | "agencyDealershipName" | "mealPreference" | "customAnswers" | "customDetailAnswers"
>): string | null {
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
