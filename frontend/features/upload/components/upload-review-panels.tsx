"use client";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import { Button } from "@/components/ui/button";
import { isUploadFieldRequired, type RequiredUploadField } from "@/features/passports/types/upload-configuration";
import type { PassportSubmission } from "@/types/passport.types";
import { ArrowLeft } from "lucide-react";
import type { ComponentProps, Dispatch, SetStateAction } from "react";
import type { useUploadContactVerification } from "../hooks/use-upload-contact-verification";
import type { useUploadDocuments } from "../hooks/use-upload-documents";
import type { getUploadFlowSettings } from "../services/configured-upload";
import type { FamilyMemberUpdate } from "../services/family-upload-state";
import { passportDocumentVerificationGate } from "../services/passport-document-verification";
import type { SingleReviewDraft } from "../services/review-submission-validation";
import { isClientSubmissionComplete } from "../services/upload-flow-helpers";
import { SavedUploadDocuments } from "./saved-upload-documents";
import { VerifiedContactSummary } from "./upload-contact-verification";
import { ConfiguredClientFields, CustomDetailFields, CustomQuestionFields, DepartureCitySelect, NameInput } from "./upload-flow-fields";
import { DocumentVerificationBlock, ExtractionNotice, ReviewFields, ReviewLayout, ReviewWarning } from "./upload-flow-review";
import { ErrorMessage } from "./upload-flow-shell";
import type { FamilyMember, UploadFlowStep } from "./upload-flow.types";

type Set<T> = Dispatch<SetStateAction<T>>;
type CommonProps = {
  token: string; settings: ReturnType<typeof getUploadFlowSettings>;
  documents: Pick<ReturnType<typeof useUploadDocuments>, "extractingSubmissionId" | "handleScanAgain" | "handleFamilyScanAgain" | "replaceSavedPassport" | "isScanningAgain" | "isReplacingSavedPassport">;
  contactVerification: Pick<ReturnType<typeof useUploadContactVerification>, "edit">;
  canReviewSubmission: (saved: PassportSubmission) => boolean; uploadError: string | null;
  departureCity: string; setDepartureCity: Set<string>; onSubmit: (event: React.FormEvent) => Promise<void>;
};
type SingleProps = CommonProps & {
  submission: PassportSubmission; singleUploadIdempotencyKey: string; review: SingleReviewDraft;
  configuredFields: ComponentProps<typeof ConfiguredClientFields>;
  requiresPassportReview: (saved: PassportSubmission) => boolean;
  extractionNotice: string | null; canRetryExtraction: boolean; setClientName: Set<string>;
  handleReviewFieldChange: (key: string, value: string) => void;
  setCustomAnswers: Set<Record<string, string>>; setCustomDetailAnswers: Set<Record<string, string>>;
};
type FamilyProps = CommonProps & {
  familyMembers: FamilyMember[]; hasBlockedFamilyVerification: boolean; setStep: Set<UploadFlowStep>;
  selectFamilyMember: (index: number) => void; updateFamilyMember: (index: number, update: FamilyMemberUpdate) => void;
  handleFamilyReviewFieldChange: (index: number, key: string, value: string) => void;
};

export function UploadSingleReview({ token, settings, documents, contactVerification, canReviewSubmission, uploadError,
  departureCity, setDepartureCity, onSubmit: handleFinalSubmit, submission, singleUploadIdempotencyKey, review,
  configuredFields, requiresPassportReview, extractionNotice, canRetryExtraction, setClientName,
  handleReviewFieldChange, setCustomAnswers, setCustomDetailAnswers }: SingleProps) {
  const { clientName, clientEmail, clientPhone, reviewFields, customAnswers, customDetailAnswers } = review;
  const { extractingSubmissionId, handleScanAgain, replaceSavedPassport, isScanningAgain, isReplacingSavedPassport } = documents;
  const { uploadConfig, airportEnabled, departureCities, enabledCustomQuestions, enabledCustomDetails } = settings;
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  const verificationGate = passportDocumentVerificationGate(submission);
  const reviewAllowed = canReviewSubmission(submission);
  const hasPassport = requiresPassportReview(submission);
  return (
    <ReviewLayout
      title={!hasPassport ? "Review Traveller Details" : reviewAllowed
        ? "Verify Passport Details"
        : "Passport Verification Required"}
      description={reviewAllowed
        ? "Please check every field carefully before submitting."
        : "The saved upload must be verified before any passport details can be reviewed or submitted."}
      documents={<SavedUploadDocuments submission={submission} token={token} uploadSessionId={singleUploadIdempotencyKey} />}
      onBack={() => contactVerification.edit(submission.id)}
    >
      {!reviewAllowed && !verificationGate.accepted ? (
        <div className="rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-6">
          {extractingSubmissionId === submission.id && <ProcessingMotion variant="passport" compact className="mx-auto mb-4" />}
          <DocumentVerificationBlock
            gate={verificationGate}
            onRetry={() => void handleScanAgain()}
            onReplace={() => void replaceSavedPassport(null)}
            isRetrying={isScanningAgain}
            isReplacing={isReplacingSavedPassport}
          />
          <ErrorMessage message={uploadError} />
        </div>
      ) : (
        <form onSubmit={handleFinalSubmit} className="rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-6">
          {extractingSubmissionId === submission.id && <ProcessingMotion variant="passport" compact className="mx-auto mb-4" />}
          {hasPassport && <ReviewWarning />}
          <ExtractionNotice message={extractionNotice} />
          <ErrorMessage message={uploadError} />
          {canRetryExtraction && (
            <div className="mb-5 rounded-xl border border-blue-100 bg-blue-50 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm font-medium text-blue-800">
                  Automatic reading failed or timed out. Your saved image can be retried without uploading it again.
                </p>
                <Button type="button" variant="secondary" size="sm" onClick={handleScanAgain} disabled={isScanningAgain}>
                  {isScanningAgain ? "Reading saved image" : "Retry automatic reading"}
                </Button>
              </div>
            </div>
          )}
          {hasPassport ? <ReviewFields fields={reviewFields} onChange={handleReviewFieldChange} /> : (
            <label className="block space-y-2 text-sm font-semibold text-slate-700">Full name *<NameInput value={clientName} onChange={(value) => { setClientName(value); handleReviewFieldChange("given_names", value); }} /></label>
          )}
          <VerifiedContactSummary email={clientEmail} phone={clientPhone} onEdit={() => contactVerification.edit(submission.id)} />
          {airportEnabled && <DepartureCitySelect value={departureCity} cities={departureCities} onChange={setDepartureCity} className="mt-4" required={requiredField("departure_city")} />}
          <ConfiguredClientFields {...configuredFields} />
          <CustomQuestionFields
            questions={enabledCustomQuestions}
            answers={customAnswers}
            onChange={(questionId, value) => setCustomAnswers((current) => ({
              ...current,
              [questionId]: value,
            }))}
          />
          <CustomDetailFields
            details={enabledCustomDetails}
            answers={customDetailAnswers}
            onChange={(detailId, value) => setCustomDetailAnswers((current) => ({
              ...current,
              [detailId]: value,
            }))}
          />
          <Button
            type="submit"
            size="lg"
            disabled={isScanningAgain}
            className="mt-6 h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
          >
            {submission.manual_review_submission_allowed ? "Submit for AI verification" : hasPassport ? "Submit Verified Details" : "Submit Traveller Details"}
          </Button>
        </form>
      )}
    </ReviewLayout>
  );
}

export function UploadFamilyReview({ token, settings, documents, contactVerification, canReviewSubmission, uploadError,
  departureCity, setDepartureCity, onSubmit: handleFamilySubmit, familyMembers, hasBlockedFamilyVerification,
  setStep, selectFamilyMember, updateFamilyMember, handleFamilyReviewFieldChange }: FamilyProps) {
  const { extractingSubmissionId, handleFamilyScanAgain, replaceSavedPassport, isScanningAgain, isReplacingSavedPassport } = documents;
  const { uploadConfig, airportEnabled, departureCities, baseCityEnabled, askNearestDomesticAirport,
    staffCodeEnabled, agentEmployeeCodeEnabled, designationEnabled, agencyDealershipNameEnabled,
    mealPreferenceEnabled, enabledCustomQuestions, enabledCustomDetails } = settings;
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  return (
    <div className="min-h-screen bg-slate-50 px-3 py-4 font-sans sm:px-4 sm:py-10">
      <form onSubmit={handleFamilySubmit} className="mx-auto w-full max-w-5xl space-y-4 sm:space-y-5">
        <button type="button" onClick={() => setStep("METHOD_SELECT")} className="inline-flex items-center gap-2 text-sm font-medium text-slate-600">
          <ArrowLeft className="h-4 w-4" />
          Back to uploads
        </button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Review Family Details</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">Check all family member details together before final submission.</p>
        </div>
        <ErrorMessage message={uploadError} />
        {familyMembers.map((member, index) => {
          const verificationGate = member.submission
            ? passportDocumentVerificationGate(member.submission)
            : null;
          const reviewAllowed = Boolean(member.submission && canReviewSubmission(member.submission));
          const hasPassport = Boolean(member.submission?.image_s3_key);
          return (
            <fieldset key={member.localId} disabled={Boolean(member.submission && isClientSubmissionComplete(member.submission))} className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
              <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <h2 className="text-lg font-bold text-slate-900">{member.name}</h2>
                  <p className="text-sm text-slate-500">{member.relation} • {member.gender}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    selectFamilyMember(index);
                    setStep("METHOD_SELECT");
                  }}
                  className="inline-flex h-9 items-center justify-center rounded-lg border border-blue-100 bg-blue-50 px-3 text-sm font-semibold text-blue-700"
                >
                  {member.submission ? "Review document options" : "Continue document step"}
                </button>
              </div>
              {extractingSubmissionId === member.submission?.id && <ProcessingMotion variant="passport" compact className="mx-auto mb-4" />}
              <div className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
                {member.submission ? <SavedUploadDocuments submission={member.submission} token={token} uploadSessionId={member.uploadIdempotencyKey} /> : <p className="text-sm text-slate-500">Complete this member&apos;s document step to continue.</p>}
                {!verificationGate ? (
                  <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium leading-6 text-amber-950">
                    Complete this member&apos;s document step before reviewing their details.
                  </div>
                ) : !reviewAllowed && !verificationGate.accepted ? (
                  <DocumentVerificationBlock
                    gate={verificationGate}
                    onRetry={() => void handleFamilyScanAgain(index)}
                    onReplace={() => void replaceSavedPassport(index)}
                    isRetrying={isScanningAgain}
                    isReplacing={isReplacingSavedPassport}
                  />
                ) : (
                  <div>
                    {hasPassport && <ReviewWarning />}
                    <ExtractionNotice message={member.extractionNotice} />
                    {member.canRetryExtraction && (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="mb-4"
                        onClick={() => handleFamilyScanAgain(index)}
                        disabled={isScanningAgain}
                      >
                        {isScanningAgain ? "Reading saved image" : "Retry reading saved image"}
                      </Button>
                    )}
                    {hasPassport ? <ReviewFields fields={member.reviewFields} onChange={(key, value) => handleFamilyReviewFieldChange(index, key, value)} /> : <label className="block space-y-2 text-sm font-semibold text-slate-700">Full name *<NameInput value={member.name} onChange={(value) => { updateFamilyMember(index, { name: value }); handleFamilyReviewFieldChange(index, "given_names", value); }} /></label>}
                  </div>
                )}
              </div>
              {reviewAllowed && (
                <>
                  <VerifiedContactSummary email={member.email} phone={member.phone} onEdit={() => { if (member.submission) contactVerification.edit(member.submission.id); }} />
                  <ConfiguredClientFields
                    config={uploadConfig}
                    baseCityEnabled={baseCityEnabled}
                    askNearestDomesticAirport={askNearestDomesticAirport}
                    staffCodeEnabled={staffCodeEnabled}
                    agentEmployeeCodeEnabled={agentEmployeeCodeEnabled}
                    designationEnabled={designationEnabled}
                    agencyDealershipNameEnabled={agencyDealershipNameEnabled}
                    mealPreferenceEnabled={mealPreferenceEnabled}
                    baseCity={member.baseCity}
                    nearestDomesticAirport={member.nearestDomesticAirport}
                    staffCode={member.staffCode}
                    agentEmployeeType={member.agentEmployeeType}
                    agentEmployeeCode={member.agentEmployeeCode}
                    designation={member.designation}
                    agencyDealershipName={member.agencyDealershipName}
                    mealPreference={member.mealPreference}
                    onBaseCity={(value) => updateFamilyMember(index, { baseCity: value })}
                    onNearestDomesticAirport={(value) => updateFamilyMember(index, { nearestDomesticAirport: value })}
                    onStaffCode={(value) => updateFamilyMember(index, { staffCode: value })}
                    onAgentEmployeeType={(value) => updateFamilyMember(index, { agentEmployeeType: value })}
                    onAgentEmployeeCode={(value) => updateFamilyMember(index, { agentEmployeeCode: value })}
                    onDesignation={(value) => updateFamilyMember(index, { designation: value })}
                    onAgencyDealershipName={(value) => updateFamilyMember(index, { agencyDealershipName: value })}
                    onMealPreference={(value) => updateFamilyMember(index, { mealPreference: value })}
                  />
                  <CustomQuestionFields
                    questions={enabledCustomQuestions}
                    answers={member.customAnswers}
                    onChange={(questionId, value) => updateFamilyMember(index, {
                      customAnswers: {
                        ...member.customAnswers,
                        [questionId]: value,
                      },
                    })}
                  />
                  <CustomDetailFields
                    details={enabledCustomDetails}
                    answers={member.customDetailAnswers}
                    onChange={(detailId, value) => updateFamilyMember(index, {
                      customDetailAnswers: {
                        ...member.customDetailAnswers,
                        [detailId]: value,
                      },
                    })}
                  />
                </>
              )}
            </fieldset>
          );
        })}
        {!hasBlockedFamilyVerification ? (
          <>
            <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
              <h2 className="text-lg font-bold text-slate-900">Head of family contact</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">The first member’s verified email and WhatsApp number are used as the head of family contact. Tickets and visas are sent to each member’s verified number.</p>
              {airportEnabled && (
                <DepartureCitySelect value={departureCity} cities={departureCities} onChange={setDepartureCity} className="mt-4" required={requiredField("departure_city")} />
              )}
            </section>
            <Button
              type="submit"
              size="lg"
              disabled={isScanningAgain}
              className="h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
            >
              {familyMembers.some((member) => member.submission?.manual_review_submission_allowed) ? "Submit family for AI verification" : "Submit Family Details"}
            </Button>
          </>
        ) : (
          <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium leading-6 text-amber-950">
            Resolve every passport verification issue above before reviewing contact details or submitting this family.
          </div>
        )}
      </form>
    </div>
  );
}
