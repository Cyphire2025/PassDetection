"use client";

import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import { cleanPassportReviewFields as cleanReviewFields } from "@/features/passports/utils/passport-review";
import { apiErrorStatus } from "@/lib/api/error-status";
import type { PassportSubmission } from "@/types/passport.types";
import type { Dispatch, SetStateAction } from "react";
import type { FamilyMember, UploadFlowStep } from "../components/upload-flow.types";
import type { getUploadFlowSettings } from "../services/configured-upload";
import { isClientSubmissionComplete, passportHolderName, submitErrorMessage } from "../services/upload-flow-helpers";
import { useSubmitClientPassportReview } from "./use-upload";
import { isContactVerificationError, type useUploadContactVerification } from "./use-upload-contact-verification";
import type { useUploadOperation } from "./use-upload-operation";

import { validateFamilyReview, validateSingleReview, type SingleReviewDraft } from "../services/review-submission-validation";

type Set<T> = Dispatch<SetStateAction<T>>;
type Context = {
  token: string; submission: PassportSubmission | null; singleUploadIdempotencyKey: string;
  familyMembers: FamilyMember[]; familyGroupId: string;
  updateFamilyMember: (index: number, patch: Partial<FamilyMember>) => void;
  contactVerification: Pick<ReturnType<typeof useUploadContactVerification>, "getProof" | "edit" | "invalidate">;
  operation: ReturnType<typeof useUploadOperation>;
  setSubmission: Set<PassportSubmission | null>; setClientName: Set<string>; setStep: Set<UploadFlowStep>;
  setUploadError: Set<string | null>; setLinkError: Set<unknown>;
  canReviewSubmission: (value: PassportSubmission) => boolean;
  requiresPassportReview: (value: PassportSubmission) => boolean;
  settings: ReturnType<typeof getUploadFlowSettings>; draft: SingleReviewDraft;
};

/** Submission preserves every acknowledged family member before attempting the next. */
export function useUploadSubmission({ token, submission, singleUploadIdempotencyKey, familyMembers, familyGroupId, updateFamilyMember, contactVerification, operation, setSubmission, setClientName, setStep, setUploadError, setLinkError, canReviewSubmission, requiresPassportReview, settings, draft }: Context) {
  const { mutateAsync: submitClientReview } = useSubmitClientPassportReview();
  const { clientEmail, clientPhone, reviewFields, departureCity, baseCity, nearestDomesticAirport, staffCode, agentEmployeeCode, designation, agencyDealershipName, mealPreference, customAnswers, customDetailAnswers } = draft;
  const { enabledCustomQuestions, enabledCustomDetails } = settings;
  const handleFinalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!submission || operation.isBusy()) return;
    const contactProof = contactVerification.getProof(submission.id, singleUploadIdempotencyKey, clientEmail, clientPhone);
    if (!contactProof) { contactVerification.edit(submission.id); return; }
    const validationError = validateSingleReview({ submission, settings, draft, canReviewSubmission, requiresPassportReview });
    if (validationError) { setUploadError(validationError); return; }

    const pending = operation.begin("submit");
    if (!pending) return;
    try {
      setUploadError(null);
      setStep("SUBMITTING");
      const submitted = await submitClientReview({
        submissionId: submission.id,
        uploadSessionId: singleUploadIdempotencyKey,
        group_token: token,
        confirmed_fields: cleanReviewFields(reviewFields),
        client_email: clientEmail,
        client_phone: clientPhone,
        phone_verification_id: contactProof.id,
        departure_city: departureCity || null,
        base_city: baseCity.trim() || null,
        nearest_domestic_airport: nearestDomesticAirport.trim() || null,
        staff_code: staffCode.trim() || null,
        agent_employee_type: null,
        agent_employee_code: agentEmployeeCode || null,
        designation: designation.trim() || null,
        agency_dealership_name: agencyDealershipName.trim() || null,
        meal_preference: mealPreference || null,
        submission_mode: "single",
        custom_answers: enabledCustomQuestions.filter((question) => customAnswers[question.id]?.trim()).map((question) => ({
          question_id: question.id,
          value: customAnswers[question.id],
        })),
        custom_detail_answers: enabledCustomDetails.filter((detail) => customDetailAnswers[detail.id]?.trim()).map((detail) => ({
          detail_id: detail.id,
          value: customDetailAnswers[detail.id],
        })),
      });
      if (!operation.isCurrent(pending)) return;
      setSubmission(submitted);
      setClientName(passportHolderName(reviewFields));
      setStep("SUCCESS");
    } catch (error: unknown) {
      if (!operation.isCurrent(pending)) return;
      setUploadError(submitErrorMessage(error));
      if (isContactVerificationError(error)) contactVerification.invalidate(submission.id);
      setStep("REVIEW");
      if ([404, 410].includes(apiErrorStatus(error) ?? 0)) {
        await uploadLinksApi.getByToken(token).catch((linkError: unknown) => {
          if (operation.isCurrent(pending)) setLinkError(linkError);
        });
      }
    } finally {
      operation.finish(pending);
    }
  };

  const handleFamilySubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (operation.isBusy()) return;
    const headEmail = familyMembers[0]?.email ?? "";
    const headPhone = familyMembers[0]?.phone ?? "";
    const unverified = familyMembers.find((member) => member.submission && !isClientSubmissionComplete(member.submission) && !contactVerification.getProof(member.submission.id, member.uploadIdempotencyKey, member.email, member.phone));
    if (unverified?.submission) { contactVerification.edit(unverified.submission.id); return; }
    const validationError = validateFamilyReview({ familyMembers, settings, draft, canReviewSubmission, requiresPassportReview });
    if (validationError) { setUploadError(validationError); return; }

    const pending = operation.begin("submit");
    if (!pending) return;
    try {
      setUploadError(null);
      setStep("SUBMITTING");
      for (const [index, member] of familyMembers.entries()) {
        if (!member.submission || isClientSubmissionComplete(member.submission)) continue;
        const contactProof = contactVerification.getProof(member.submission.id, member.uploadIdempotencyKey, member.email, member.phone);
        if (!contactProof) throw { code: "CONTACT_VERIFICATION_REQUIRED", message: "Verify your WhatsApp number again before submitting." };
        const submitted = await submitClientReview({
          submissionId: member.submission.id,
          uploadSessionId: member.uploadIdempotencyKey,
          group_token: token,
          confirmed_fields: cleanReviewFields(member.reviewFields),
          client_email: member.email.trim(),
          client_phone: member.phone.trim(),
          phone_verification_id: contactProof.id,
          departure_city: departureCity || null,
          base_city: member.baseCity.trim() || null,
          nearest_domestic_airport: member.nearestDomesticAirport.trim() || null,
          staff_code: member.staffCode.trim() || null,
          agent_employee_type: null,
          agent_employee_code: member.agentEmployeeCode || null,
          designation: member.designation.trim() || null,
          agency_dealership_name:
            member.agencyDealershipName.trim() || null,
          meal_preference: member.mealPreference || null,
          submission_mode: "family",
          family_group_id: familyGroupId,
          family_member_index: index,
          family_relation: member.relation,
          family_gender: member.gender,
          family_head_name: familyMembers[0]?.name || member.name,
          family_head_email: headEmail,
          family_head_phone: headPhone,
          custom_answers: enabledCustomQuestions.filter((question) => member.customAnswers[question.id]?.trim()).map((question) => ({
            question_id: question.id,
            value: member.customAnswers[question.id],
          })),
          custom_detail_answers: enabledCustomDetails.filter((detail) => member.customDetailAnswers[detail.id]?.trim()).map((detail) => ({
            detail_id: detail.id,
            value: member.customDetailAnswers[detail.id],
          })),
        });
        if (!operation.isCurrent(pending)) return;
        updateFamilyMember(index, { submission: submitted });
      }
      setStep("SUCCESS");
    } catch (error: unknown) {
      if (!operation.isCurrent(pending)) return;
      setUploadError(submitErrorMessage(error));
      if (isContactVerificationError(error)) familyMembers.forEach((member) => { if (member.submission) contactVerification.invalidate(member.submission.id); });
      setStep("FAMILY_REVIEW");
      if ([404, 410].includes(apiErrorStatus(error) ?? 0)) {
        await uploadLinksApi.getByToken(token).catch((linkError: unknown) => {
          if (operation.isCurrent(pending)) setLinkError(linkError);
        });
      }
    } finally {
      operation.finish(pending);
    }
  };

  return { handleFinalSubmit, handleFamilySubmit };
}
