import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import type { PassportSubmission } from "@/types/passport.types";
import { uploadApi } from "../api/upload.api";
import { qualifierChoiceKey, type QualifierPath } from "./relation-qualifier";
import {
  applyUploadReconciliation,
  createUploadRecoveryRecord,
  uploadRecoveryTarget,
} from "./upload-recovery";
import {
  canRetryExtractionFor,
  errorMessage,
  extractionNoticeFor,
  getInitialReviewFields,
  isClientSubmissionComplete,
  isExtractionTerminal,
  passportHolderName,
  stageLabel,
} from "./upload-flow-helpers";
import {
  clearQualifierSelectionToken,
  createIdempotencyKey,
  isMissingSavedSubmissionError,
  isPermanentQualifierRestoreError,
  readQualifierSelectionToken,
  readUploadRecoveryRecord,
  writeUploadRecoveryRecord,
} from "./upload-flow-session";
import type {
  FlowMode,
  UploadFlowStep,
} from "../components/upload-flow.types";

type RecoveryTelemetryEvent =
  | "recovery_started"
  | "recovery_succeeded"
  | "recovery_missed";

interface UploadFlowBootstrapActions {
  setSingleUploadIdempotencyKey: (value: string) => void;
  setSubmission: (value: PassportSubmission) => void;
  setClientName: (value: string) => void;
  setStep: (value: UploadFlowStep) => void;
  setReviewFields: (value: Record<string, string>) => void;
  setExtractionNotice: (value: string | null) => void;
  setCanRetryExtraction: (value: boolean) => void;
  setProcessingProgress: (value: number) => void;
  setProcessingStage: (value: string) => void;
  queueSubmissionResume: (value: PassportSubmission) => void;
  setFlowMode: (value: FlowMode) => void;
  setUploadError: (value: string) => void;
  setQualifierSelectionToken: (value: string | null) => void;
  setPersistedQualifierChoice: (value: string | null) => void;
  setQualifierPath: (value: QualifierPath) => void;
  setQualifierRelationCode: (value: string) => void;
}

interface RunUploadFlowBootstrapOptions {
  token: string;
  relationWithQualifierEnabled: boolean;
  isCancelled: () => boolean;
  reportPublicFlowOnce: (event: RecoveryTelemetryEvent) => void;
  actions: UploadFlowBootstrapActions;
}

export async function runUploadFlowBootstrap({
  token,
  relationWithQualifierEnabled,
  isCancelled,
  reportPublicFlowOnce,
  actions,
}: RunUploadFlowBootstrapOptions) {
  // Yield once so all initialization state changes happen from the external
  // session/API synchronization callback, not synchronously in an effect body.
  await Promise.resolve();
  if (isCancelled()) return;

  const storedRecovery = readUploadRecoveryRecord(token);
  const recovery = storedRecovery
    ?? createUploadRecoveryRecord(createIdempotencyKey());
  actions.setSingleUploadIdempotencyKey(recovery.idempotencyKey);
  if (!storedRecovery) writeUploadRecoveryRecord(token, recovery);

  const restoreSubmission = async (submissionId: string) => {
    try {
      const savedSubmission = await uploadApi.getUploadStatus(
        token,
        submissionId,
        recovery.idempotencyKey,
      );
      if (isCancelled()) return;
      reportPublicFlowOnce("recovery_succeeded");
      writeUploadRecoveryRecord(
        token,
        createUploadRecoveryRecord(recovery.idempotencyKey, savedSubmission.id),
      );
      actions.setSubmission(savedSubmission);
      actions.setClientName(
        passportHolderName(
          savedSubmission.confirmed_fields
          ?? savedSubmission.extracted_fields,
        )
        || (
          savedSubmission.client_name === "Passport holder"
            ? ""
            : savedSubmission.client_name
        ),
      );
      if (isClientSubmissionComplete(savedSubmission)) {
        actions.setStep("SUCCESS");
        return;
      }
      if (isExtractionTerminal(savedSubmission)) {
        actions.setReviewFields(
          getInitialReviewFields(savedSubmission.extracted_fields),
        );
        actions.setExtractionNotice(extractionNoticeFor(savedSubmission));
        actions.setCanRetryExtraction(canRetryExtractionFor(savedSubmission));
        actions.setStep("REVIEW");
        return;
      }
      actions.setProcessingProgress(
        savedSubmission.processing_progress ?? 0.05,
      );
      actions.setProcessingStage(stageLabel(
        savedSubmission.processing_stage
        ?? savedSubmission.processing_job_status
        ?? "queued",
      ));
      actions.queueSubmissionResume(savedSubmission);
      actions.setStep("UPLOADING");
    } catch (restoreError: unknown) {
      if (isCancelled()) return;
      reportPublicFlowOnce("recovery_missed");
      if (isMissingSavedSubmissionError(restoreError)) {
        const replacement = createUploadRecoveryRecord(createIdempotencyKey());
        writeUploadRecoveryRecord(token, replacement);
        actions.setSingleUploadIdempotencyKey(replacement.idempotencyKey);
        actions.setUploadError(
          "The previous saved upload is no longer available. Please start a new upload.",
        );
        if (relationWithQualifierEnabled) {
          clearQualifierSelectionToken(token);
          actions.setQualifierSelectionToken(null);
          actions.setPersistedQualifierChoice(null);
          actions.setStep("QUALIFIER_SELECT");
        } else {
          actions.setStep("MODE_SELECT");
        }
        return;
      }
      actions.setUploadError(errorMessage(
        restoreError,
        "Your saved passport upload could not be reached. Retry reconnecting; a new upload has not been started.",
      ));
      actions.setStep("RECOVERY_ERROR");
    }
  };

  const recoveryTarget = uploadRecoveryTarget(recovery);
  if (storedRecovery) {
    reportPublicFlowOnce("recovery_started");
  }
  if (storedRecovery && recoveryTarget.kind === "attempt") {
    try {
      const reconciled = await uploadApi.reconcileUpload(
        token,
        recoveryTarget.idempotencyKey,
      );
      if (isCancelled()) return;
      const reconciledRecovery = applyUploadReconciliation(
        recovery,
        reconciled.submission_id,
      );
      if (reconciledRecovery.submissionId) {
        writeUploadRecoveryRecord(token, reconciledRecovery);
        actions.setFlowMode("single");
        await restoreSubmission(reconciledRecovery.submissionId);
        return;
      }
      reportPublicFlowOnce("recovery_missed");
    } catch (reconciliationError: unknown) {
      if (isCancelled()) return;
      reportPublicFlowOnce("recovery_missed");
      actions.setUploadError(errorMessage(
        reconciliationError,
        "We could not check whether your previous upload was saved. Retry reconnecting before selecting the passport files again.",
      ));
      actions.setStep("RECOVERY_ERROR");
      return;
    }
  }

  // A durable submission is already bound to this browser's private upload
  // credential. Restore it before consulting the short-lived qualifier
  // selection token so refresh/back navigation cannot create a second
  // relationship choice for an upload that was safely persisted.
  if (recovery.submissionId) {
    actions.setFlowMode("single");
    await restoreSubmission(recovery.submissionId);
    return;
  }

  if (!relationWithQualifierEnabled) {
    actions.setStep("MODE_SELECT");
    return;
  }

  actions.setFlowMode("single");
  const storedToken = readQualifierSelectionToken(token);
  if (!storedToken) {
    actions.setStep("QUALIFIER_SELECT");
    return;
  }

  let selection: Awaited<
    ReturnType<typeof uploadLinksApi.getQualifierSelection>
  >;
  try {
    selection = await uploadLinksApi.getQualifierSelection(token, storedToken);
  } catch (restoreError: unknown) {
    if (isCancelled()) return;
    if (isPermanentQualifierRestoreError(restoreError)) {
      clearQualifierSelectionToken(token);
      actions.setQualifierSelectionToken(null);
      actions.setPersistedQualifierChoice(null);
      actions.setUploadError(
        "Your previous relationship choice is no longer available. Please choose again.",
      );
      actions.setStep("QUALIFIER_SELECT");
      return;
    }
    actions.setQualifierSelectionToken(storedToken);
    actions.setUploadError(errorMessage(
      restoreError,
      "Your saved relationship choice could not be reached. Retry reconnecting; it has not been discarded.",
    ));
    actions.setStep("RECOVERY_ERROR");
    return;
  }
  if (isCancelled()) return;
  if (selection.status === "expired") {
    clearQualifierSelectionToken(token);
    actions.setQualifierSelectionToken(null);
    actions.setPersistedQualifierChoice(null);
    actions.setUploadError(
      "Your previous relationship choice expired. Please choose again.",
    );
    actions.setStep("QUALIFIER_SELECT");
    return;
  }

  actions.setQualifierSelectionToken(storedToken);
  actions.setQualifierPath(selection.is_self ? "self" : "relation");
  actions.setQualifierRelationCode(selection.relation_code ?? "");
  actions.setPersistedQualifierChoice(qualifierChoiceKey(
    selection.is_self ? "self" : "relation",
    selection.relation_code ?? "",
  ));

  if (selection.status === "active" || !selection.submission_id) {
    actions.setStep("METHOD_SELECT");
    return;
  }

  writeUploadRecoveryRecord(
    token,
    createUploadRecoveryRecord(recovery.idempotencyKey, selection.submission_id),
  );
  await restoreSubmission(selection.submission_id);
}
