"use client";
import dynamic from "next/dynamic";
import { AlertCircle } from "lucide-react";
import {
  canRetryPassportAiVerification,
  buildStaffApprovalRequest,
  getPassportReviewerLabel,
  getStaffApprovalOutcomeFeedback,
} from "../utils/passport-review";
import { needsReextraction } from "../utils/passport-reextract";
import { ClientProvidedFieldsCard } from "./client-provided-fields-card";
import { PassportDetailHeader, PassportDetailLoading, PassportDetailError } from "./passport-detail-header";
import { PassportDetailImages } from "./passport-detail-images";
import { PassportAttendanceQrCard } from "./passport-attendance-qr-card";
import { ReviewFieldsCard } from "./passport-review-card";
import { usePassportDetailController } from "./use-passport-detail-controller";
import { getExtractionConflicts } from "./passport-review-model";

const PassportImageCropEditor = dynamic(
  () => import("./passport-image-crop-editor").then((module) => module.PassportImageCropEditor),
  { loading: () => null },
);

export function PassportDetail({ id, navigationQuery = "" }: { id: string; navigationQuery?: string }) {
  const {
    data, isLoading, error, refetch, currentUser, canCropPassportImages, confirmMutation, staffApproveMutation,
    retryAiVerificationMutation, reextractMutation, formError, setFormError, approvalFeedback, setApprovalFeedback,
    reextractFeedback, cropEditor, setCropEditor, imageRevision, setImageRevision, changingImageType,
    imageChangeErrors, navigation, handleReextract, handleManualImageChange,
  } = usePassportDetailController(id, navigationQuery);
  if (isLoading) return <PassportDetailLoading />;
  if (error || !data) return <PassportDetailError />;

  return (
    <div className="flex flex-col gap-5">
      <PassportDetailHeader data={data} navigation={navigation} />


      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <PassportDetailImages data={data} imageRevision={imageRevision} canCropPassportImages={canCropPassportImages}
          changingImageType={changingImageType} imageChangeErrors={imageChangeErrors}
          handleManualImageChange={handleManualImageChange} setCropEditor={setCropEditor} />


        <div className="flex flex-col gap-6">
          <PassportAttendanceQrCard data={data} />


          <ClientProvidedFieldsCard passport={data} canEdit={canCropPassportImages} />

          <ReviewFieldsCard
            key={`${data.id}:${data.extraction_revision}:${data.updated_at}`}
            passport={data}
            sourceFields={data.confirmed_fields ?? data.extracted_fields ?? {}}
            validation={data.extracted_fields?.field_validation}
            conflicts={getExtractionConflicts(data)}
            isSaving={confirmMutation.isPending || staffApproveMutation.isPending}
            canRetryAiVerification={canRetryPassportAiVerification(data)}
            isRetryingAiVerification={retryAiVerificationMutation.isPending}
            canReextract={needsReextraction(data)}
            isReextracting={reextractMutation.isPending}
            reextractFeedback={reextractFeedback}
            approvalFeedback={approvalFeedback}
            formError={formError}
            onFormError={setFormError}
            onConfirm={(fields) => confirmMutation.mutateAsync(fields)}
            onStaffApprove={async (fields, reviewReason) => {
              setApprovalFeedback(null);
              const result = await staffApproveMutation.mutateAsync(
                buildStaffApprovalRequest(
                  fields,
                  data.extraction_revision,
                  reviewReason,
                ),
              );
              setApprovalFeedback(
                getStaffApprovalOutcomeFeedback(result.outcome),
              );
              return result;
            }}
            onRetryAiVerification={() => retryAiVerificationMutation.mutateAsync()}
            reviewerLabel={getPassportReviewerLabel(data, currentUser)}
            onReextract={() => void handleReextract()}
          />

          {data.error_message && !["submitted", "ai_approved", "staff_approved", "confirmed"].includes(data.status) && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{data.error_message}</span>
              </div>
            </div>
          )}
        </div>
      </div>
      {cropEditor && canCropPassportImages && (
        <PassportImageCropEditor
          submissionId={data.id}
          imageType={cropEditor.imageType}
          label={cropEditor.label}
          returnFocusTarget={cropEditor.returnFocusTarget}
          onClose={() => setCropEditor(null)}
          onSaved={() => {
            setImageRevision((current) => current + 1);
            void refetch();
          }}
        />
      )}
    </div>
  );
}
