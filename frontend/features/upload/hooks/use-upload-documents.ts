"use client";

import { MAX_PASSPORT_UPLOAD_BYTES } from "@/features/passports/types/upload-configuration";
import type { PassportSubmission } from "@/types/passport.types";
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { uploadApi } from "../api/upload.api";
import type { ExtractionWaitResult, FamilyMember, FlowMode, PassportDocumentBundle, UploadFlowStep } from "../components/upload-flow.types";
import { normalizePassportFile } from "../services/passport-perspective-correction";
import { pollSavedPassport } from "../services/saved-passport-extraction";
import { canRetryExtractionFor, emptyDocumentBundle, errorMessage, extractionNoticeFor, getInitialReviewFields, isExtractionTerminal, mergeMissingReviewFields, passportHolderName, uploadPersistenceErrorMessage } from "../services/upload-flow-helpers";
import { createIdempotencyKey, writeUploadRecoveryRecord } from "../services/upload-flow-session";
import { createUploadRecoveryRecord } from "../services/upload-recovery";
import { useUploadPassport } from "./use-upload";
import type { useUploadOperation } from "./use-upload-operation";

import type { FamilyMemberUpdate } from "../services/family-upload-state";

type Set<T> = Dispatch<SetStateAction<T>>;
type Context = {
  token: string; step: UploadFlowStep; flowMode: FlowMode | null; activeFamilyIndex: number;
  familyMembers: FamilyMember[]; updateFamilyMember: (index: number, update: FamilyMemberUpdate) => void;
  clientName: string; setClientName: Set<string>;
  submission: PassportSubmission | null; setSubmission: Set<PassportSubmission | null>;
  setReviewFields: Set<Record<string, string>>;
  singleUploadIdempotencyKey: string; setSingleUploadIdempotencyKey: Set<string>;
  qualifierSelectionToken: string | null; activeVisaPhotoSource: "camera" | "file" | null;
  setVisaSelfie: Set<File | null>; setDocumentBundle: Set<PassportDocumentBundle>;
  selectFamilyMember: (index: number) => void; setStep: Set<UploadFlowStep>;
  setUploadError: Set<string | null>; setExtractionNotice: Set<string | null>; setCanRetryExtraction: Set<boolean>;
  operation: ReturnType<typeof useUploadOperation>;
};

/** Saved-document persistence, extraction and replacement share one cancellable operation. */
export function useUploadDocuments({ token, step, flowMode, activeFamilyIndex, familyMembers, updateFamilyMember, clientName, setClientName, submission, setSubmission, setReviewFields, singleUploadIdempotencyKey, setSingleUploadIdempotencyKey, qualifierSelectionToken, activeVisaPhotoSource, setVisaSelfie, setDocumentBundle, selectFamilyMember, setStep, setUploadError, setExtractionNotice, setCanRetryExtraction, operation }: Context) {
  const { mutateAsync: uploadPassport } = useUploadPassport();
  const activeFamilyMember = familyMembers[activeFamilyIndex] ?? null;
  const [processingProgress, setProcessingProgress] = useState<number | null>(null);
  const [processingStage, setProcessingStage] = useState("Uploading securely");
  const [extractingSubmissionId, setExtractingSubmissionId] = useState<string | null>(null);
  const [isPreparingFile, setIsPreparingFile] = useState(false);
  const [resumeSubmissionId, setResumeSubmissionId] = useState<string | null>(null);
  const resumeSubmissionRef = useRef<PassportSubmission | null>(null);
  const resumeInFlightRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  const { begin, isCurrent, finish, cancel, isBusy } = operation;
  const isScanningAgain = operation.state.status === "active" && operation.state.kind === "retry";
  const isReplacingSavedPassport = operation.state.status === "active" && operation.state.kind === "replace";
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const queueSubmissionResume = useCallback((saved: PassportSubmission) => { resumeSubmissionRef.current = saved; setResumeSubmissionId(saved.id); }, []);
  const processUpload = async (
    file: File | null,
    passportBackFile: File | null,
    acquisitionMode: "camera" | "file",
    frontSource: "camera" | "file",
    frontManuallyCropped: boolean,
    passportPhotoFile?: File | null,
    passportCoverFile?: File | null,
    passportBackCoverFile?: File | null,
  ) => {
    if (isBusy()) return;
    const uploadName = flowMode === "family"
      ? activeFamilyMember?.name
      : (clientName.trim() || (file ? "Passport holder" : ""));
    if (!uploadName || uploadName.trim().length < 2) {
      setUploadError("Enter the passenger name before uploading.");
      return;
    }
    const familyIndex = flowMode === "family" ? activeFamilyIndex : null;
    const uploadIdempotencyKey = familyIndex === null
      ? singleUploadIdempotencyKey
      : familyMembers[familyIndex]?.uploadIdempotencyKey;
    if (!uploadIdempotencyKey) {
      setUploadError("Could not prepare a safe upload attempt. Please try again.");
      return;
    }

    const pending = begin("upload");
    if (!pending) return;
    if (familyIndex === null) {
      writeUploadRecoveryRecord(
        token,
        createUploadRecoveryRecord(uploadIdempotencyKey),
      );
    }
    const controller = pending.controller;
    const stageTimers: number[] = [];
    let persisted: PassportSubmission | null = null;
    try {
      setUploadError(null);
      setExtractionNotice(null);
      setCanRetryExtraction(false);
      setIsPreparingFile(true);
      // Live camera files and browser-cropped device files have already passed
      // exact-final-image validation. Mixed bundles still report
      // acquisitionMode "file", so keep the chosen manual crop unchanged and
      // only run legacy perspective correction for an undecodable original.
      const normalizedFrontFile = !file || frontSource === "camera" || frontManuallyCropped
        ? file
        : (await normalizePassportFile(file)).file;
      const preparedFrontFile = acquisitionMode === "file" && normalizedFrontFile && normalizedFrontFile.size > MAX_PASSPORT_UPLOAD_BYTES
        ? file
        : normalizedFrontFile;
      if (!mountedRef.current || controller.signal.aborted) return;
      setIsPreparingFile(false);
      setProcessingProgress(null);
      setProcessingStage("Validating and saving your passport pages securely.");
      setStep("UPLOADING");
      stageTimers.push(window.setTimeout(() => {
        if (mountedRef.current && !controller.signal.aborted) {
          setProcessingStage("Saving is taking a little longer. It is safe to keep this page open.");
        }
      }, 3_000));
      stageTimers.push(window.setTimeout(() => {
        if (mountedRef.current && !controller.signal.aborted) {
          setProcessingStage("Still confirming secure file storage. Please do not submit the same pages again yet.");
        }
      }, 15_000));
      persisted = await uploadPassport({
        token,
        client_name: uploadName.trim(),
        file: preparedFrontFile,
        passportPhotoFile,
        passportBackFile,
        passportCoverFile,
        passportBackCoverFile,
        visaPhotoSource: activeVisaPhotoSource,
        acquisitionMode,
        uploadIdempotencyKey,
        qualifierSelectionToken,
        signal: controller.signal,
      });
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      stageTimers.length = 0;
      if (!mountedRef.current || controller.signal.aborted) return;

      if (familyIndex === null) {
        writeUploadRecoveryRecord(
          token,
          createUploadRecoveryRecord(uploadIdempotencyKey, persisted.id),
        );
      }
      if (familyIndex === null) {
        setSubmission(persisted);
      } else {
        // Keep the server acknowledgement even if extraction is cancelled.
        // Family state is session-local; single-mode recovery is persisted above.
        updateFamilyMember(familyIndex, { submission: persisted });
      }
      setProcessingProgress(persisted.processing_progress ?? 0.05);
      setProcessingStage("Passport pages saved. Reading available details for review.");
      const waitResult = !file || isExtractionTerminal(persisted)
        ? {
          submission: persisted,
          notice: extractionNoticeFor(persisted),
          retryAllowed: canRetryExtractionFor(persisted),
        }
        : await waitForExtraction(
          persisted,
          uploadIdempotencyKey,
          controller.signal,
          familyIndex === null,
        );
      const completed = waitResult.submission;
      if (!mountedRef.current || controller.signal.aborted) return;
      setDocumentBundle(emptyDocumentBundle());

      if (familyIndex !== null) {
        const fields = file ? getInitialReviewFields(completed.extracted_fields) : { given_names: uploadName.trim() };
        updateFamilyMember(familyIndex, {
          submission: completed,
          reviewFields: fields,
          visaSelfie: null,
          extractionNotice: waitResult.notice,
          canRetryExtraction: waitResult.retryAllowed,
        });
        const nextIndex = familyMembers.findIndex(
          (member, index) => index !== familyIndex && !member.submission,
        );
        if (nextIndex >= 0) {
          selectFamilyMember(nextIndex);
          setStep("METHOD_SELECT");
        } else {
          setStep("FAMILY_REVIEW");
        }
        return;
      }

      setSubmission(completed);
      setExtractionNotice(waitResult.notice);
      setCanRetryExtraction(waitResult.retryAllowed);
      setVisaSelfie(null);
      const fields = file ? getInitialReviewFields(completed.extracted_fields) : { given_names: uploadName.trim() };
      setReviewFields(fields);
      setClientName(passportHolderName(fields) || uploadName.trim());
      setStep("REVIEW");
    } catch (error: unknown) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setIsPreparingFile(false);
      setProcessingProgress(null);
      setProcessingStage("Uploading securely");
      if (persisted) {
        const notice = "Automatic passport detail extraction failed. Your passport images are saved. Retry automatic reading or enter the details manually.";
        if (familyIndex !== null) {
          const fields = getInitialReviewFields(persisted.extracted_fields);
          updateFamilyMember(familyIndex, {
            submission: persisted,
            reviewFields: fields,
            visaSelfie: null,
            extractionNotice: notice,
            canRetryExtraction: true,
          });
          setStep("FAMILY_REVIEW");
        } else {
          setSubmission(persisted);
          const fields = getInitialReviewFields(persisted.extracted_fields);
          setReviewFields(fields);
          setClientName(passportHolderName(fields));
          setExtractionNotice(notice);
          setCanRetryExtraction(true);
          setStep("REVIEW");
        }
      } else {
        setUploadError(uploadPersistenceErrorMessage(error));
        setStep("METHOD_SELECT");
      }
    } finally {
      stageTimers.forEach((timer) => window.clearTimeout(timer));
      finish(pending);
    }
  };

  const waitForExtraction = useCallback(async (
    initial: PassportSubmission,
    uploadSessionId: string,
    signal: AbortSignal,
    updateSingleReview = true,
  ): Promise<ExtractionWaitResult> => {
    // Saved-job state drives extraction labels and recovery. The full-screen
    // artwork stays mounted through preparation, upload and this polling phase.
    if (mountedRef.current && !signal.aborted) setExtractingSubmissionId(initial.id);
    try {
      return await pollSavedPassport({
        initial,
        signal,
        fetchStatus: (submissionId, currentSignal) => uploadApi.getUploadStatus(token, submissionId, uploadSessionId, currentSignal),
        onProgress: (current, progress, stage) => {
          if (!mountedRef.current || signal.aborted) return;
          if (updateSingleReview) setSubmission(current);
          setProcessingProgress(progress);
          setProcessingStage(stage);
        },
      });
    } finally {
      if (mountedRef.current && !signal.aborted) {
        setExtractingSubmissionId((current) => current === initial.id ? null : current);
      }
    }
  }, [token, setSubmission]);

  useEffect(() => {
    if (
      !resumeSubmissionId
      || step !== "UPLOADING"
      || resumeInFlightRef.current === resumeSubmissionId
    ) {
      return;
    }
    const savedSubmission = resumeSubmissionRef.current;
    if (!savedSubmission || savedSubmission.id !== resumeSubmissionId) return;
    resumeInFlightRef.current = resumeSubmissionId;
    const pending = begin("resume");
    if (!pending) { resumeInFlightRef.current = null; return; }
    const controller = pending.controller;
    const clearResumeState = () => {
      if (resumeInFlightRef.current !== savedSubmission.id) return;
      resumeInFlightRef.current = null;
      resumeSubmissionRef.current = null;
      setResumeSubmissionId((current) => (
        current === savedSubmission.id ? null : current
      ));
    };

    void waitForExtraction(
      savedSubmission,
      singleUploadIdempotencyKey,
      controller.signal,
    )
      .then((result) => {
        if (!mountedRef.current || controller.signal.aborted) return;
        setSubmission(result.submission);
        setReviewFields(getInitialReviewFields(result.submission.extracted_fields));
        setExtractionNotice(result.notice);
        setCanRetryExtraction(result.retryAllowed);
        clearResumeState();
        setStep("REVIEW");
      })
      .catch((resumeError: unknown) => {
        if (!mountedRef.current || controller.signal.aborted) return;
        setReviewFields(getInitialReviewFields(savedSubmission.extracted_fields));
        setExtractionNotice(
          "Your passport pages are saved. Enter the details manually or retry reading the stored image.",
        );
        setCanRetryExtraction(true);
        setUploadError(errorMessage(
          resumeError,
          "The saved upload could not reconnect automatically.",
        ));
        clearResumeState();
        setStep("REVIEW");
      })
      .finally(() => {
        finish(pending);
      });

    return () => {
      controller.abort();
      finish(pending);
      if (resumeInFlightRef.current === resumeSubmissionId) resumeInFlightRef.current = null;
    };
  }, [
    resumeSubmissionId,
    singleUploadIdempotencyKey,
    step,
    waitForExtraction, begin, finish, setCanRetryExtraction, setExtractionNotice, setReviewFields, setStep, setSubmission, setUploadError,
  ]);

  const retrySavedExtraction = async (familyIndex: number | null) => {
    const member = familyIndex === null ? null : familyMembers[familyIndex];
    const saved = familyIndex === null ? submission : member?.submission;
    if (!saved) return;
    const pending = begin("retry");
    if (!pending) return;
    const notice = "Retrying automatic reading from the passport image that is already saved.";
    const credential = familyIndex === null ? singleUploadIdempotencyKey : member?.uploadIdempotencyKey;
    try {
      setUploadError(null);
      setExtractingSubmissionId(saved.id);
      if (familyIndex === null) setExtractionNotice(notice);
      else updateFamilyMember(familyIndex, { extractionNotice: notice });
      if (!credential) throw new Error("The secure upload credential is unavailable.");
      const queued = await uploadApi.scanAgain(token, saved.id, credential, pending.controller.signal);
      const result = isExtractionTerminal(queued)
        ? { submission: queued, notice: extractionNoticeFor(queued), retryAllowed: canRetryExtractionFor(queued) }
        : await waitForExtraction(queued, credential, pending.controller.signal, familyIndex === null);
      if (!isCurrent(pending)) return;
      if (familyIndex === null) {
        setSubmission(result.submission);
        setExtractionNotice(result.notice);
        setCanRetryExtraction(result.retryAllowed);
        setReviewFields((current) => mergeMissingReviewFields(current, result.submission.extracted_fields));
      } else {
        updateFamilyMember(familyIndex, (current) => ({
          submission: result.submission,
          reviewFields: mergeMissingReviewFields(current.reviewFields, result.submission.extracted_fields),
          extractionNotice: result.notice, canRetryExtraction: result.retryAllowed,
        }));
      }
    } catch (error: unknown) {
      if (isCurrent(pending)) setUploadError(errorMessage(error, "Could not scan the stored passport again. Please try again."));
    } finally {
      if (isCurrent(pending)) setExtractingSubmissionId((current) => current === saved.id ? null : current);
      finish(pending);
    }
  };
  const handleScanAgain = () => retrySavedExtraction(null);
  const handleFamilyScanAgain = (index: number) => retrySavedExtraction(index);

  const handleBackToUploadMethods = () => {
    cancel();
    setIsPreparingFile(false);
    setExtractingSubmissionId(null);
    setUploadError(null);
    setProcessingProgress(null);
    setProcessingStage("Uploading securely");
    setStep("METHOD_SELECT");
  };

  const replaceSavedPassport = async (
    targetFamilyIndex: number | null = flowMode === "family"
      ? activeFamilyIndex
      : null,
  ) => {
    const savedSubmission = targetFamilyIndex !== null
      ? familyMembers[targetFamilyIndex]?.submission ?? null
      : submission;
    const uploadSessionId = targetFamilyIndex !== null
      ? familyMembers[targetFamilyIndex]?.uploadIdempotencyKey
      : singleUploadIdempotencyKey;
    if (
      !savedSubmission
      || !uploadSessionId
      || isBusy()
    ) return;
    cancel();
    const pending = begin("replace");
    if (!pending) return;
    try {
      setUploadError(null);
      await uploadApi.discardUpload(
        token,
        savedSubmission.id,
        uploadSessionId,
      );
      if (!isCurrent(pending)) return;
      setDocumentBundle(emptyDocumentBundle());
      if (targetFamilyIndex !== null) {
        updateFamilyMember(targetFamilyIndex, {
          submission: null,
          reviewFields: {},
          extractionNotice: null,
          canRetryExtraction: false,
          uploadIdempotencyKey: createIdempotencyKey(),
        });
        selectFamilyMember(targetFamilyIndex);
      } else {
        const replacementIdempotencyKey = createIdempotencyKey();
        setSubmission(null);
        setReviewFields({});
        setExtractionNotice(null);
        setCanRetryExtraction(false);
        setSingleUploadIdempotencyKey(replacementIdempotencyKey);
        writeUploadRecoveryRecord(
          token,
          createUploadRecoveryRecord(replacementIdempotencyKey),
        );
      }
      setStep("METHOD_SELECT");
    } catch (error: unknown) {
      if (isCurrent(pending)) {
        setUploadError(errorMessage(
          error,
          "The saved passport could not be replaced safely. It has been preserved; please try again.",
        ));
      }
    } finally {
      finish(pending);
    }
  };

  return {
    processUpload, handleScanAgain, handleFamilyScanAgain, handleBackToUploadMethods, replaceSavedPassport,
    processingProgress, setProcessingProgress, processingStage, setProcessingStage, extractingSubmissionId,
    isPreparingFile, isScanningAgain, isReplacingSavedPassport, resumeSubmissionId, queueSubmissionResume
  };
}
