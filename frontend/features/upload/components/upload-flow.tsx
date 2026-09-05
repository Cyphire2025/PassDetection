"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Mail,
  Phone,
  User,
  Users,
} from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import {
  cleanPassportReviewFields as cleanReviewFields,
} from "@/features/passports/utils/passport-review";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PassportSubmission } from "@/types/passport.types";
import { isUploadFieldRequired, MAX_PASSPORT_UPLOAD_BYTES, type RequiredUploadField } from "@/features/passports/types/upload-configuration";
import { passportBundleError, getUploadFlowSettings } from "../services/configured-upload";
import { PassportUploadPage } from "./passport-upload-page";
import { useSubmitClientPassportReview, useUploadPassport } from "../hooks/use-upload";
import { usePublicFlowTelemetry } from "../hooks/use-public-flow-telemetry";
import { uploadApi } from "../api/upload.api";
import { normalizePassportFile } from "../services/passport-perspective-correction";
import {
  buildQualifierSelectionRequest,
  qualifierChoiceKey,
  type QualifierPath,
} from "../services/relation-qualifier";
import {
  createUploadRecoveryRecord,
} from "../services/upload-recovery";
import {
  passportDocumentVerificationGate,
} from "../services/passport-document-verification";
import {
  canRetryExtractionFor,
  createFamilyMembers,
  emptyDocumentBundle,
  errorMessage,
  extractionNoticeFor,
  getInitialReviewFields,
  hasMissingRequiredFields,
  hasValidReviewDates,
  isExtractionTerminal,
  mergeMissingReviewFields,
  passportHolderName,
  resizeFamilyMembers,
  sleep,
  stageLabel,
  submitErrorMessage,
  uploadPersistenceErrorMessage,
} from "../services/upload-flow-helpers";
import {
  clearQualifierSelectionToken,
  createIdempotencyKey,
  readUploadRecoveryRecord,
  writeQualifierSelectionToken,
  writeUploadRecoveryRecord,
} from "../services/upload-flow-session";
import { runUploadFlowBootstrap } from "../services/upload-flow-bootstrap";
import {
  EXTRACTION_POLL_INITIAL_DELAY_MS,
  EXTRACTION_POLL_WINDOW_MS,
  isTransientExtractionPollError,
  nextExtractionPollDelay,
} from "./extraction-polling";
import { RelationQualifierStep } from "./relation-qualifier-step";
import { SavedUploadDocuments } from "./saved-upload-documents";
import { UploadDocumentOptions } from "./upload-flow-document-options";
import {
  FAMILY_RELATIONS,
  GENDERS,
  PASSIVE_PROGRESS_STEPS,
} from "./upload-flow.constants";
import {
  ConfiguredClientFields,
  ContactInput,
  ContactSection,
  CustomDetailFields,
  CustomQuestionFields,
  DepartureCitySelect,
  NameInput,
  SelectInput,
} from "./upload-flow-fields";
import {
  SavedPassportActions,
  VisaSelfieChoice,
} from "./upload-flow-passport-picker";
import {
  DocumentVerificationBlock,
  ExtractionNotice,
  ReviewFields,
  ReviewLayout,
  ReviewWarning,
} from "./upload-flow-review";
import {
  BackButton,
  CenteredLoader,
  CenteredShell,
  ChoiceCard,
  ErrorMessage,
  ProcessingScreen,
  UploadHeader,
} from "./upload-flow-shell";
import type {
  AgentEmployeeType,
  ExtractionWaitResult,
  FamilyMember,
  FlowMode,
  PassportDocumentBundle,
  PendingPassportCrop,
  UploadFlowStep as Step,
} from "./upload-flow.types";

const PassportManualCrop = dynamic(
  () => import("./passport-manual-crop").then((module) => module.PassportManualCrop),
  { loading: () => <CenteredLoader /> },
);
const SmartCamera = dynamic(
  () => import("./smart-camera").then((module) => module.SmartCamera),
  { loading: () => <CenteredLoader /> },
);
const VisaPhotoUpload = dynamic(
  () => import("./visa-photo-upload").then((module) => module.VisaPhotoUpload),
  { loading: () => <CenteredLoader /> },
);
const VisaSelfieCamera = dynamic(
  () => import("./visa-selfie-camera").then((module) => module.VisaSelfieCamera),
  { loading: () => <CenteredLoader /> },
);

interface UploadFlowProps {
  token: string;
}

export function UploadFlow({ token }: UploadFlowProps) {
  const { data: group, isLoading, error } = useUploadLinkByToken(token);
  const { mutateAsync: uploadPassport } = useUploadPassport();
  const { mutateAsync: submitClientReview } = useSubmitClientPassportReview();

  const [step, setStep] = useState<Step>("BOOTSTRAP");
  const [flowMode, setFlowMode] = useState<FlowMode | null>(null);
  const [qualifierPath, setQualifierPath] = useState<QualifierPath>(null);
  const [qualifierRelationCode, setQualifierRelationCode] = useState("");
  const [qualifierSelectionToken, setQualifierSelectionToken] = useState<string | null>(null);
  const [persistedQualifierChoice, setPersistedQualifierChoice] = useState<string | null>(null);
  const [isSavingQualifier, setIsSavingQualifier] = useState(false);
  const [resumeSubmissionId, setResumeSubmissionId] = useState<string | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [departureCity, setDepartureCity] = useState("");
  const [baseCity, setBaseCity] = useState("");
  const [nearestDomesticAirport, setNearestDomesticAirport] = useState("");
  const [staffCode, setStaffCode] = useState("");
  const [agentEmployeeType, setAgentEmployeeType] = useState<AgentEmployeeType>("");
  const [agentEmployeeCode, setAgentEmployeeCode] = useState("");
  const [designation, setDesignation] = useState("");
  const [agencyDealershipName, setAgencyDealershipName] = useState("");
  const [mealPreference, setMealPreference] = useState("");
  const [customAnswers, setCustomAnswers] = useState<Record<string, string>>({});
  const [customDetailAnswers, setCustomDetailAnswers] = useState<Record<string, string>>({});
  const [submission, setSubmission] = useState<PassportSubmission | null>(null);
  const [reviewFields, setReviewFields] = useState<Record<string, string>>({});
  const [singleUploadIdempotencyKey, setSingleUploadIdempotencyKey] = useState(
    () => readUploadRecoveryRecord(token)?.idempotencyKey ?? createIdempotencyKey(),
  );
  const [recoveryRetryNonce, setRecoveryRetryNonce] = useState(0);
  const [extractionNotice, setExtractionNotice] = useState<string | null>(null);
  const [canRetryExtraction, setCanRetryExtraction] = useState(false);

  const [familyGroupId] = useState(() => (typeof crypto !== "undefined" ? crypto.randomUUID() : `${Date.now()}`));
  const [familyCountInput, setFamilyCountInput] = useState("2");
  const [familyMembers, setFamilyMembers] = useState<FamilyMember[]>(() => createFamilyMembers(2));
  const [activeFamilyIndex, setActiveFamilyIndex] = useState(0);
  const [headEmail, setHeadEmail] = useState("");
  const [headPhone, setHeadPhone] = useState("");

  const [uploadError, setUploadError] = useState<string | null>(null);
  const [processingProgress, setProcessingProgress] = useState<number | null>(null);
  const [processingStage, setProcessingStage] = useState<string>("Uploading securely");
  const [isPreparingFile, setIsPreparingFile] = useState(false);
  const [isScanningAgain, setIsScanningAgain] = useState(false);
  const [isReplacingSavedPassport, setIsReplacingSavedPassport] = useState(false);
  const [visaSelfie, setVisaSelfie] = useState<File | null>(null);
  const [visaPhotoSource, setVisaPhotoSource] = useState<"camera" | "file" | null>(null);
  const [passportMethod, setPassportMethod] = useState<"camera" | "file">("camera");
  const [documentBundle, setDocumentBundle] = useState<PassportDocumentBundle>(() => emptyDocumentBundle());
  const [scannerPageSide, setScannerPageSide] = useState<"front" | "back">("front");
  const [pendingPassportCrop, setPendingPassportCrop] = useState<PendingPassportCrop | null>(null);
  const mountedRef = useRef(false);
  const operationInFlightRef = useRef(false);
  const requestControllerRef = useRef<AbortController | null>(null);
  const scanAgainInFlightRef = useRef(false);
  const qualifierSaveInFlightRef = useRef(false);
  const initializedGroupTokenRef = useRef<string | null>(null);
  const resumeSubmissionRef = useRef<PassportSubmission | null>(null);
  const resumeInFlightRef = useRef<string | null>(null);
  const {
    uploadConfig, groupId, airportEnabled, departureCities,
    baseCityEnabled, staffCodeEnabled, agentEmployeeCodeEnabled, designationEnabled,
    agencyDealershipNameEnabled, mealPreferenceEnabled, selfieEnabled, selfieRequired,
    passportEnabled, passportRequired, allowFilesFromDevice, askNearestDomesticAirport,
    relationWithQualifierEnabled, enabledCustomQuestions, enabledCustomDetails,
  } = getUploadFlowSettings(group);
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  const activeFamilyMember = familyMembers[activeFamilyIndex] ?? null;
  const activeVisaSelfie = flowMode === "family" ? activeFamilyMember?.visaSelfie ?? null : visaSelfie;
  const activeVisaPhotoSource = flowMode === "family" ? activeFamilyMember?.visaPhotoSource ?? null : visaPhotoSource;
  const requiresPassportReview = (saved: PassportSubmission) => Boolean(saved.image_s3_key);
  const canReviewSubmission = (saved: PassportSubmission) => requiresPassportReview(saved)
    ? passportDocumentVerificationGate(saved).accepted
    : !passportRequired || (allowFilesFromDevice && !uploadConfig.passport_upload_pages.includes("front"));
  const hasBlockedFamilyVerification = familyMembers.some((member) => (
    member.submission === null
    || !canReviewSubmission(member.submission)
  ));
  const hasActiveProgress = step !== "SUCCESS" && (
    submission !== null
    || familyMembers.some((member) => member.submission !== null)
    || qualifierSelectionToken !== null
    || clientName.trim().length > 0
    || !PASSIVE_PROGRESS_STEPS.has(step)
  );
  const {
    report: reportTelemetry,
    reportPublicFlowOnce,
  } = usePublicFlowTelemetry(token, hasActiveProgress);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!groupId || initializedGroupTokenRef.current === token) return;
    initializedGroupTokenRef.current = token;

    let cancelled = false;
    void runUploadFlowBootstrap({
      token,
      relationWithQualifierEnabled,
      isCancelled: () => cancelled,
      reportPublicFlowOnce,
      actions: {
        setSingleUploadIdempotencyKey,
        setSubmission,
        setClientName,
        setStep,
        setReviewFields,
        setExtractionNotice,
        setCanRetryExtraction,
        setProcessingProgress,
        setProcessingStage,
        queueSubmissionResume: (savedSubmission) => {
          resumeSubmissionRef.current = savedSubmission;
          setResumeSubmissionId(savedSubmission.id);
        },
        setFlowMode,
        setUploadError,
        setQualifierSelectionToken,
        setPersistedQualifierChoice,
        setQualifierPath,
        setQualifierRelationCode,
      },
    });

    return () => {
      cancelled = true;
      if (initializedGroupTokenRef.current === token) {
        initializedGroupTokenRef.current = null;
      }
    };
  }, [
    groupId,
    recoveryRetryNonce,
    relationWithQualifierEnabled,
    reportPublicFlowOnce,
    token,
  ]);

  const saveQualifierChoice = async () => {
    if (qualifierSaveInFlightRef.current) return;
    const selectionRequest = buildQualifierSelectionRequest(
      qualifierPath,
      qualifierRelationCode,
      group?.qualifier_relation_options ?? [],
    );
    if (!selectionRequest || qualifierPath === null) return;
    const choiceKey = qualifierChoiceKey(qualifierPath, qualifierRelationCode);
    if (qualifierSelectionToken && persistedQualifierChoice === choiceKey) {
      setStep("METHOD_SELECT");
      return;
    }
    qualifierSaveInFlightRef.current = true;
    setIsSavingQualifier(true);
    setUploadError(null);
    try {
      const selection = await uploadLinksApi.createQualifierSelection(token, {
        ...selectionRequest,
      });
      setQualifierSelectionToken(selection.selection_token);
      setPersistedQualifierChoice(choiceKey);
      writeQualifierSelectionToken(token, selection.selection_token);
      setFlowMode("single");
      setStep("METHOD_SELECT");
    } catch (selectionError: unknown) {
      setUploadError(errorMessage(
        selectionError,
        "Could not save the relationship choice. Please try again.",
      ));
    } finally {
      qualifierSaveInFlightRef.current = false;
      setIsSavingQualifier(false);
    }
  };

  const selectFamilyMember = (index: number) => {
    setActiveFamilyIndex(index);
    setDocumentBundle(emptyDocumentBundle());
    setPendingPassportCrop(null);
    setUploadError(null);
  };

  const chooseMode = (mode: FlowMode) => {
    setFlowMode(mode);
    setUploadError(null);
    setStep(mode === "single" ? "METHOD_SELECT" : "FAMILY_SETUP");
  };

  const updateFamilyCount = (count: number) => {
    const safeCount = Math.max(2, Math.min(20, count));
    setFamilyCountInput(String(safeCount));
    setFamilyMembers((current) => resizeFamilyMembers(current, safeCount));
  };

  const handleFamilyCountInput = (value: string) => {
    if (!/^\d*$/.test(value)) return;
    setFamilyCountInput(value);
    if (!value) return;
    const count = Number(value);
    if (Number.isNaN(count)) return;
    if (count >= 2 && count <= 20) {
      setFamilyMembers((current) => resizeFamilyMembers(current, count));
    }
  };

  const normalizeFamilyCountInput = () => {
    const count = Number(familyCountInput);
    updateFamilyCount(Number.isNaN(count) ? 2 : count);
  };

  const updateFamilyMember = (index: number, patch: Partial<FamilyMember>) => {
    setFamilyMembers((current) => current.map((member, itemIndex) => itemIndex === index ? { ...member, ...patch } : member));
  };

  const startFamilyUploads = (event: React.FormEvent) => {
    event.preventDefault();
    const invalidMember = familyMembers.find((member) => member.name.trim().length < 2 || !member.relation || !member.gender);
    if (invalidMember) {
      setUploadError("Enter name, relation, and gender for every family member.");
      return;
    }
    if (!headEmail.trim() && familyMembers[0]?.email.trim()) setHeadEmail(familyMembers[0].email.trim());
    if (!headPhone.trim() && familyMembers[0]?.phone.trim()) setHeadPhone(familyMembers[0].phone.trim());
    setUploadError(null);
    selectFamilyMember(familyMembers.findIndex((member) => !member.submission) === -1 ? 0 : familyMembers.findIndex((member) => !member.submission));
    setStep("METHOD_SELECT");
  };

  const handleBundleUpload = async () => {
    const bundleError = passportBundleError(documentBundle, uploadConfig, passportMethod);
    if (bundleError) {
      setUploadError(bundleError);
      return;
    }
    if (selfieRequired && !activeVisaSelfie) {
      setUploadError("Capture or upload the required Visa Photo before continuing.");
      return;
    }
    const acquisitionMode = passportMethod;
    if (!allowFilesFromDevice && acquisitionMode !== "camera") {
      setUploadError("This group requires both passport pages to be captured with the live scanner.");
      return;
    }
    await processUpload(
      documentBundle.front,
      documentBundle.back,
      acquisitionMode,
      documentBundle.frontSource ?? "file",
      documentBundle.frontManuallyCropped,
      activeVisaSelfie,
      documentBundle.cover,
      documentBundle.back_cover,
    );
  };

  const continueWithoutPassport = async () => {
    if (passportRequired) return;
    if (selfieRequired && !activeVisaSelfie) {
      setUploadError("Please add the required Visa Photo before continuing.");
      return;
    }
    await processUpload(null, null, "file", "file", false, activeVisaSelfie);
  };

  const beginPassportCrop = (
    file: File,
    pageSide: "front" | "back",
    source: "camera" | "file",
  ) => {
    /*
     * Manual passport cropping is intentionally unwired from upload links.
     * Keep this activation code available for a future controlled rollout:
     *
     * setPendingPassportCrop({ file, pageSide, source });
     * setUploadError(null);
     * setStep("PASSPORT_CROP");
     * return;
     */
    setDocumentBundle((current) => ({
      ...current,
      [pageSide]: file,
      [`${pageSide}Source`]: source,
      [`${pageSide}ManuallyCropped`]: false,
    }));
    setUploadError(null);
    if (source === "camera" && pageSide === "front" && !documentBundle.back) {
      setScannerPageSide("back");
      setStep("CAMERA");
      return;
    }
    setStep("METHOD_SELECT");
  };

  const handleCameraCapture = (file: File) => {
    beginPassportCrop(file, scannerPageSide, "camera");
  };

  const handlePassportCropConfirm = (
    croppedFile: File,
    manuallyCropped: boolean,
  ) => {
    if (!pendingPassportCrop) return;
    const { pageSide, source } = pendingPassportCrop;
    setDocumentBundle((current) => ({
      ...current,
      [pageSide]: croppedFile,
      [`${pageSide}Source`]: source,
      [`${pageSide}ManuallyCropped`]: manuallyCropped,
    }));
    setPendingPassportCrop(null);
    setUploadError(null);
    if (source === "camera" && pageSide === "front" && !documentBundle.back) {
      setScannerPageSide("back");
      setStep("CAMERA");
      return;
    }
    setStep("METHOD_SELECT");
  };

  const handlePassportCropCancel = () => {
    const pending = pendingPassportCrop;
    setPendingPassportCrop(null);
    setUploadError(null);
    if (pending?.source === "camera") {
      setScannerPageSide(pending.pageSide);
      setStep("CAMERA");
      return;
    }
    setStep("METHOD_SELECT");
  };

  const openPassportScanner = (pageSide: "front" | "back") => {
    if (!passportEnabled || !uploadConfig.passport_live_scan) return;
    setPassportMethod("camera");
    if (passportMethod !== "camera") setDocumentBundle(emptyDocumentBundle());
    setScannerPageSide(pageSide);
    setUploadError(null);
    setStep("CAMERA");
  };

  const handleSelfieCapture = (file: File, source: "camera" | "file") => {
    setUploadError(null);
    if (flowMode === "family") {
      setFamilyMembers((current) => current.map((member, index) => (
        index === activeFamilyIndex ? { ...member, visaSelfie: file, visaPhotoSource: source } : member
      )));
    } else {
      setVisaSelfie(file);
      setVisaPhotoSource(source);
    }
    setStep("METHOD_SELECT");
  };

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
    if (operationInFlightRef.current) return;
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

    operationInFlightRef.current = true;
    if (familyIndex === null) {
      writeUploadRecoveryRecord(
        token,
        createUploadRecoveryRecord(uploadIdempotencyKey),
      );
    }
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
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
        if (mountedRef.current) {
          setProcessingStage("Saving is taking a little longer. It is safe to keep this page open.");
        }
      }, 3_000));
      stageTimers.push(window.setTimeout(() => {
        if (mountedRef.current) {
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
      if (familyIndex === null) setSubmission(persisted);
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
        setFamilyMembers((current) => current.map((member, index) => (
          index === familyIndex
            ? {
              ...member,
              submission: completed,
              reviewFields: fields,
              visaSelfie: null,
              extractionNotice: waitResult.notice,
              canRetryExtraction: waitResult.retryAllowed,
            }
            : member
        )));
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
          setFamilyMembers((current) => current.map((member, index) => (
            index === familyIndex
              ? {
                ...member,
                submission: persisted,
                reviewFields: fields,
                visaSelfie: null,
                extractionNotice: notice,
                canRetryExtraction: true,
              }
              : member
          )));
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
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      operationInFlightRef.current = false;
    }
  };

  const waitForExtraction = useCallback(async (
    initial: PassportSubmission,
    uploadSessionId: string,
    signal: AbortSignal,
    updateSingleReview = true,
  ): Promise<ExtractionWaitResult> => {
    let current = initial;
    if (mountedRef.current) {
      if (updateSingleReview) setSubmission(current);
      setProcessingProgress(current.processing_progress ?? 0.05);
      setProcessingStage(stageLabel(current.processing_stage ?? current.processing_job_status ?? "queued"));
    }

    const deadline = Date.now() + EXTRACTION_POLL_WINDOW_MS;
    let delayMs = EXTRACTION_POLL_INITIAL_DELAY_MS;
    let consecutiveNetworkFailures = 0;
    while (Date.now() < deadline && !signal.aborted) {
      await sleep(delayMs, signal);
      try {
        current = await uploadApi.getUploadStatus(
          token,
          current.id,
          uploadSessionId,
          signal,
        );
        consecutiveNetworkFailures = 0;
      } catch (pollError: unknown) {
        if (signal.aborted) throw pollError;
        if (!isTransientExtractionPollError(pollError)) throw pollError;
        consecutiveNetworkFailures += 1;
        if (mountedRef.current) {
          setProcessingStage("Reconnecting to your saved passport");
        }
        delayMs = nextExtractionPollDelay(delayMs, "failure");
        continue;
      }
      if (mountedRef.current) {
        if (updateSingleReview) setSubmission(current);
        setProcessingProgress(current.processing_progress ?? null);
        setProcessingStage(stageLabel(current.processing_stage ?? current.processing_job_status ?? "processing"));
      }

      if (isExtractionTerminal(current)) {
        if (mountedRef.current) setProcessingProgress(1);
        return {
          submission: current,
          notice: extractionNoticeFor(current),
          retryAllowed: canRetryExtractionFor(current),
        };
      }
      delayMs = nextExtractionPollDelay(delayMs, "success");
    }
    if (signal.aborted) throw new DOMException("Operation cancelled", "AbortError");

    // Reconcile once without a delay at the boundary. This prevents the UI
    // from presenting stale empty fields when the worker completed during the
    // final backoff interval.
    try {
      current = await uploadApi.getUploadStatus(
        token,
        current.id,
        uploadSessionId,
        signal,
      );
      if (isExtractionTerminal(current)) {
        if (mountedRef.current) setProcessingProgress(1);
        return {
          submission: current,
          notice: extractionNoticeFor(current),
          retryAllowed: canRetryExtractionFor(current),
        };
      }
    } catch {
      // The durable upload remains safe. The review screen explains that
      // automatic reading could not yet be confirmed and offers a stored-image
      // retry without asking the traveller to upload again.
    }

    return {
      submission: current,
      notice: consecutiveNetworkFailures > 0
        ? "Your passport pages are saved. The connection remained unstable while checking the extracted details, so you can continue manually or retry reading the stored image."
        : "Your passport pages are saved. Automatic reading is taking longer than expected, so you can enter the details manually now or retry reading the stored image.",
      retryAllowed: true,
    };
  }, [token]);

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
    const controller = new AbortController();
    requestControllerRef.current?.abort();
    requestControllerRef.current = controller;
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
        if (requestControllerRef.current === controller) {
          requestControllerRef.current = null;
        }
      });

    return () => {
      controller.abort();
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        if (resumeInFlightRef.current === resumeSubmissionId) {
          resumeInFlightRef.current = null;
        }
      }
    };
  }, [
    resumeSubmissionId,
    singleUploadIdempotencyKey,
    step,
    waitForExtraction,
  ]);

  const handleReviewFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleFamilyReviewFieldChange = (index: number, key: string, value: string) => {
    setFamilyMembers((current) => current.map((member, itemIndex) => (
      itemIndex === index ? { ...member, reviewFields: { ...member.reviewFields, [key]: value } } : member
    )));
  };

  const handleScanAgain = async () => {
    if (!submission || isScanningAgain || scanAgainInFlightRef.current) return;
    scanAgainInFlightRef.current = true;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    try {
      setUploadError(null);
      setExtractionNotice("Retrying automatic reading from the passport image that is already saved.");
      setIsScanningAgain(true);
      const queued = await uploadApi.scanAgain(
        token,
        submission.id,
        singleUploadIdempotencyKey,
        controller.signal,
      );
      const waitResult = isExtractionTerminal(queued)
        ? {
          submission: queued,
          notice: extractionNoticeFor(queued),
          retryAllowed: canRetryExtractionFor(queued),
        }
        : await waitForExtraction(
          queued,
          singleUploadIdempotencyKey,
          controller.signal,
        );
      if (!mountedRef.current || controller.signal.aborted) return;
      setSubmission(waitResult.submission);
      setExtractionNotice(waitResult.notice);
      setCanRetryExtraction(waitResult.retryAllowed);
      setReviewFields((current) => (
        mergeMissingReviewFields(current, waitResult.submission.extracted_fields)
      ));
    } catch (error: unknown) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setUploadError(errorMessage(error, "Could not scan the stored passport again. Please try again."));
    } finally {
      scanAgainInFlightRef.current = false;
      if (mountedRef.current) setIsScanningAgain(false);
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
    }
  };

  const handleFamilyScanAgain = async (index: number) => {
    const savedSubmission = familyMembers[index]?.submission;
    if (
      !savedSubmission
      || isScanningAgain
      || scanAgainInFlightRef.current
    ) return;
    scanAgainInFlightRef.current = true;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    try {
      setUploadError(null);
      setIsScanningAgain(true);
      setFamilyMembers((current) => current.map((member, itemIndex) => (
        itemIndex === index
          ? {
            ...member,
            extractionNotice: "Retrying automatic reading from the passport image that is already saved.",
          }
          : member
      )));
      const uploadSessionId = familyMembers[index]?.uploadIdempotencyKey;
      if (!uploadSessionId) {
        throw new Error("The secure upload credential is unavailable.");
      }
      const queued = await uploadApi.scanAgain(
        token,
        savedSubmission.id,
        uploadSessionId,
        controller.signal,
      );
      const waitResult = isExtractionTerminal(queued)
        ? {
          submission: queued,
          notice: extractionNoticeFor(queued),
          retryAllowed: canRetryExtractionFor(queued),
        }
        : await waitForExtraction(
          queued,
          uploadSessionId,
          controller.signal,
          false,
        );
      if (!mountedRef.current || controller.signal.aborted) return;
      setFamilyMembers((current) => current.map((member, itemIndex) => (
        itemIndex === index
          ? {
            ...member,
            submission: waitResult.submission,
            reviewFields: mergeMissingReviewFields(
              member.reviewFields,
              waitResult.submission.extracted_fields,
            ),
            extractionNotice: waitResult.notice,
            canRetryExtraction: waitResult.retryAllowed,
          }
          : member
      )));
    } catch (error: unknown) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setUploadError(errorMessage(error, "Could not scan the stored passport again. Please try again."));
    } finally {
      scanAgainInFlightRef.current = false;
      if (mountedRef.current) setIsScanningAgain(false);
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
    }
  };

  const handleBackToUploadMethods = () => {
    requestControllerRef.current?.abort();
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
      || operationInFlightRef.current
    ) return;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setIsScanningAgain(false);
    operationInFlightRef.current = true;
    setIsReplacingSavedPassport(true);
    try {
      setUploadError(null);
      await uploadApi.discardUpload(
        token,
        savedSubmission.id,
        uploadSessionId,
      );
      if (!mountedRef.current) return;
      setDocumentBundle(emptyDocumentBundle());
      if (targetFamilyIndex !== null) {
        setFamilyMembers((current) => current.map((member, index) => (
          index === targetFamilyIndex
            ? {
              ...member,
              submission: null,
              reviewFields: {},
              extractionNotice: null,
              canRetryExtraction: false,
              uploadIdempotencyKey: createIdempotencyKey(),
            }
            : member
        )));
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
      if (mountedRef.current) {
        setUploadError(errorMessage(
          error,
          "The saved passport could not be replaced safely. It has been preserved; please try again.",
        ));
      }
    } finally {
      operationInFlightRef.current = false;
      if (mountedRef.current) setIsReplacingSavedPassport(false);
    }
  };

  const handleFinalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!submission || operationInFlightRef.current) return;
    const verificationGate = passportDocumentVerificationGate(submission);
    if (!canReviewSubmission(submission)) {
      setUploadError(verificationGate.message);
      return;
    }
    if (!requiresPassportReview(submission) && clientName.trim().length < 2) {
      setUploadError("Please enter your full name before submitting.");
      return;
    }
    if (requiresPassportReview(submission) && hasMissingRequiredFields(reviewFields)) {
      setUploadError("Please fill all required passport fields before submitting.");
      return;
    }
    if (requiresPassportReview(submission) && !hasValidReviewDates(reviewFields)) {
      setUploadError("Enter valid passport dates in DD/MM/YYYY format. Check that birth, issue, and expiry are chronological and no entered birth or issue date is in the future.");
      return;
    }
    if (airportEnabled && requiredField("departure_city") && !departureCity) {
      setUploadError("Please select your nearest international airport before submitting.");
      return;
    }
    if (baseCityEnabled && requiredField("base_city") && !baseCity.trim()) {
      setUploadError("Please enter your base city before submitting.");
      return;
    }
    if (askNearestDomesticAirport && requiredField("nearest_domestic_airport") && !nearestDomesticAirport.trim()) {
      setUploadError("Please enter your nearest domestic airport before submitting.");
      return;
    }
    if (staffCodeEnabled && requiredField("staff_code") && !staffCode.trim()) {
      setUploadError("Please enter your staff code before submitting.");
      return;
    }
    if (agentEmployeeCodeEnabled && requiredField("agent_employee_code") && !agentEmployeeCode.trim()) {
      setUploadError(`Please enter your ${uploadConfig.agent_employee_code_label.toLowerCase()}.`);
      return;
    }
    if (designationEnabled && requiredField("designation") && !designation.trim()) {
      setUploadError("Please enter your designation before submitting.");
      return;
    }
    if (agencyDealershipNameEnabled && requiredField("agency_dealership_name") && !agencyDealershipName.trim()) {
      setUploadError(`Please enter your ${uploadConfig.agency_dealership_name_label.toLowerCase()}.`);
      return;
    }
    if (mealPreferenceEnabled && requiredField("meal_preference") && !mealPreference) {
      setUploadError("Please select a meal preference before submitting.");
      return;
    }
    if (enabledCustomQuestions.some((question) => question.required !== false && !customAnswers[question.id])) {
      setUploadError("Please answer every custom question before submitting.");
      return;
    }
    if (enabledCustomDetails.some((detail) => detail.required !== false && !customDetailAnswers[detail.id]?.trim())) {
      setUploadError("Please complete every custom detail before submitting.");
      return;
    }

    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setIsScanningAgain(false);
    operationInFlightRef.current = true;
    try {
      setUploadError(null);
      setStep("SUBMITTING");
      await submitClientReview({
        submissionId: submission.id,
        uploadSessionId: singleUploadIdempotencyKey,
        group_token: token,
        confirmed_fields: cleanReviewFields(reviewFields),
        client_email: clientEmail,
        client_phone: clientPhone,
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
      setClientName(passportHolderName(reviewFields));
      setStep("SUCCESS");
    } catch (error: unknown) {
      setUploadError(submitErrorMessage(error));
      setStep("REVIEW");
    } finally {
      operationInFlightRef.current = false;
    }
  };

  const handleFamilySubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (operationInFlightRef.current) return;
    const blockedVerification = familyMembers.find((member) => (
      member.submission !== null
      && !canReviewSubmission(member.submission)
    ));
    if (blockedVerification?.submission) {
      setUploadError(
        `${blockedVerification.name || "A family member"}: ${
          passportDocumentVerificationGate(blockedVerification.submission).message
        }`,
      );
      return;
    }
    if (airportEnabled && requiredField("departure_city") && !departureCity) {
      setUploadError("Please select the family nearest international airport before submitting.");
      return;
    }
    if (!headEmail.trim() || !headPhone.trim()) {
      setUploadError("Head of family email and phone number are required.");
      return;
    }
    const missingUpload = familyMembers.find((member) => !member.submission);
    if (missingUpload) {
      setUploadError(`Upload passport for ${missingUpload.name || "every family member"} before submitting.`);
      return;
    }
    const invalidReview = familyMembers.find((member) => (
      member.submission && requiresPassportReview(member.submission) && (hasMissingRequiredFields(member.reviewFields) || !hasValidReviewDates(member.reviewFields))
    ));
    if (invalidReview) {
      setUploadError(`Fill all passport fields for ${invalidReview.name}.`);
      return;
    }
    const missingConfiguredField = familyMembers.find((member) => (
      (baseCityEnabled && requiredField("base_city") && !member.baseCity.trim())
      || (askNearestDomesticAirport && requiredField("nearest_domestic_airport") && !member.nearestDomesticAirport.trim())
      || (staffCodeEnabled && requiredField("staff_code") && !member.staffCode.trim())
      || (agentEmployeeCodeEnabled && requiredField("agent_employee_code") && !member.agentEmployeeCode.trim())
      || (designationEnabled && requiredField("designation") && !member.designation.trim())
      || (
        agencyDealershipNameEnabled
        && requiredField("agency_dealership_name")
        && !member.agencyDealershipName.trim()
      )
      || (mealPreferenceEnabled && requiredField("meal_preference") && !member.mealPreference)
      || enabledCustomQuestions.some(
        (question) => question.required !== false && !member.customAnswers[question.id],
      )
      || enabledCustomDetails.some(
        (detail) => detail.required !== false && !member.customDetailAnswers[detail.id]?.trim(),
      )
    ));
    if (missingConfiguredField) {
      setUploadError(`Complete the required group fields for ${missingConfiguredField.name}.`);
      return;
    }

    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setIsScanningAgain(false);
    operationInFlightRef.current = true;
    try {
      setUploadError(null);
      setStep("SUBMITTING");
      for (const [index, member] of familyMembers.entries()) {
        if (!member.submission) continue;
        await submitClientReview({
          submissionId: member.submission.id,
          uploadSessionId: member.uploadIdempotencyKey,
          group_token: token,
          confirmed_fields: cleanReviewFields(member.reviewFields),
          client_email: member.email.trim() || null,
          client_phone: member.phone.trim() || null,
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
      }
      setStep("SUCCESS");
    } catch (error: unknown) {
      setUploadError(submitErrorMessage(error));
      setStep("FAMILY_REVIEW");
    } finally {
      operationInFlightRef.current = false;
    }
  };

  const retrySavedUploadRecovery = () => {
    initializedGroupTokenRef.current = null;
    setUploadError(null);
    setStep("BOOTSTRAP");
    reportPublicFlowOnce("recovery_started");
    setRecoveryRetryNonce((current) => current + 1);
  };

  const documentChoices = <UploadDocumentOptions config={uploadConfig} allowFilesFromDevice={allowFilesFromDevice} flowMode={flowMode} clientName={clientName} onClientName={setClientName} passportMethod={passportMethod} bundle={documentBundle} onBundleChange={setDocumentBundle} onScan={openPassportScanner} onFileSelect={(pageSide, file) => beginPassportCrop(file, pageSide, "file")} onUpload={handleBundleUpload} onSkip={continueWithoutPassport} onOpenUpload={() => {
    if (passportMethod !== "file") setDocumentBundle(emptyDocumentBundle());
    setPassportMethod("file");
    setUploadError(null);
    setStep("PASSPORT_UPLOAD");
  }} />;

  if (isLoading || step === "BOOTSTRAP") return <CenteredLoader />;

  if (error || !group) {
    return (
      <CenteredShell>
        <div
          role="alert"
          aria-labelledby="upload-link-unavailable-title"
          className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-8 text-center shadow-lg"
        >
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
            <AlertCircle className="h-7 w-7 text-red-600" aria-hidden="true" />
          </div>
          <h2 id="upload-link-unavailable-title" className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Link Unavailable</h2>
          <p className="text-base text-slate-500">This secure group link is invalid, closed, or expired.</p>
        </div>
      </CenteredShell>
    );
  }

  if (step === "RECOVERY_ERROR") {
    return (
      <CenteredShell>
        <div className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-7 text-center shadow-lg">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-amber-100">
            <AlertCircle className="h-7 w-7 text-amber-700" aria-hidden="true" />
          </div>
          <div
            role="alert"
            aria-labelledby="upload-recovery-error-title"
            aria-atomic="true"
          >
            <h2 id="upload-recovery-error-title" className="text-xl font-bold tracking-tight text-slate-900">
              Reconnect to your saved upload
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {uploadError
                ?? "Your saved progress could not be reached. It has not been replaced or submitted again."}
            </p>
          </div>
          <Button
            type="button"
            className="mt-6 h-11 w-full"
            onClick={retrySavedUploadRecovery}
          >
            Retry reconnecting
          </Button>
          <p className="mt-3 text-xs leading-5 text-slate-400">
            If you are offline, restore your connection first. This action checks the existing upload only.
          </p>
        </div>
      </CenteredShell>
    );
  }

  if (step === "PASSPORT_CROP" && pendingPassportCrop) {
    return (
      <PassportManualCrop
        key={`${pendingPassportCrop.pageSide}:${pendingPassportCrop.source}:${pendingPassportCrop.file.name}:${pendingPassportCrop.file.lastModified}`}
        file={pendingPassportCrop.file}
        pageSide={pendingPassportCrop.pageSide}
        source={pendingPassportCrop.source}
        onConfirm={handlePassportCropConfirm}
        onCancel={handlePassportCropCancel}
      />
    );
  }

  if (step === "PASSPORT_UPLOAD" && passportEnabled && allowFilesFromDevice) {
    return <PassportUploadPage bundle={documentBundle} config={uploadConfig} onChange={setDocumentBundle} onContinue={handleBundleUpload} onBack={() => setStep("METHOD_SELECT")} error={uploadError} />;
  }

  if (step === "CAMERA") {
    return (
      <SmartCamera
        key={scannerPageSide}
        pageSide={scannerPageSide}
        allowFileFallback={false}
        onCapture={handleCameraCapture}
        onCancel={() => {
          void reportTelemetry({
            event: "public_flow",
            reason: "camera_cancelled",
          });
          setStep("METHOD_SELECT");
        }}
        onTelemetryReason={(reason) => {
          void reportTelemetry({
            event: "passport_scanner_rejection",
            reason,
          });
        }}
      />
    );
  }

  if (step === "SELFIE_CAMERA") {
    return (
      <VisaSelfieCamera
        onCapture={(file) => handleSelfieCapture(file, "camera")}
        onCancel={() => {
          void reportTelemetry({
            event: "public_flow",
            reason: "camera_cancelled",
          });
          setStep("METHOD_SELECT");
        }}
        onTelemetryReason={(reason) => {
          void reportTelemetry({
            event: "visa_photo_rejection",
            reason,
          });
        }}
      />
    );
  }

  if (step === "SELFIE_UPLOAD") {
    return (
      <VisaPhotoUpload
        onCapture={(file) => handleSelfieCapture(file, "file")}
        onCancel={() => {
          void reportTelemetry({
            event: "public_flow",
            reason: "upload_abandoned",
          });
          setStep("METHOD_SELECT");
        }}
        onTelemetryReason={(reason) => {
          void reportTelemetry({
            event: "visa_photo_rejection",
            reason,
          });
        }}
      />
    );
  }

  if (isPreparingFile) {
    return <ProcessingScreen title="Preparing Passport Image" description="Straightening the capture and optimizing it before secure upload." />;
  }

  if (step === "UPLOADING") {
    return (
      <ProcessingScreen
        title="Saving Travel Documents"
        description={processingStage}
        progress={processingProgress}
      />
    );
  }

  if (step === "SUBMITTING") {
    return <ProcessingScreen title="Submitting Reviewed Details" description="Sending your reviewed information to your travel agency." />;
  }

  if (step === "REVIEW" && submission) {
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
        onBack={handleBackToUploadMethods}
      >
        {!reviewAllowed && !verificationGate.accepted ? (
          <div className="rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-6">
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
            <ContactSection
              email={clientEmail}
              phone={clientPhone}
              departureCity={departureCity}
              departureCities={departureCities}
              onEmail={setClientEmail}
              onPhone={setClientPhone}
              onDepartureCity={setDepartureCity}
              title="Contact Details"
              departureCityRequired={requiredField("departure_city")}
              emailRequired
              phoneRequired
            />
            <ConfiguredClientFields
              config={uploadConfig}
              baseCityEnabled={baseCityEnabled}
              askNearestDomesticAirport={askNearestDomesticAirport}
              staffCodeEnabled={staffCodeEnabled}
              agentEmployeeCodeEnabled={agentEmployeeCodeEnabled}
              designationEnabled={designationEnabled}
              agencyDealershipNameEnabled={agencyDealershipNameEnabled}
              mealPreferenceEnabled={mealPreferenceEnabled}
              baseCity={baseCity}
              nearestDomesticAirport={nearestDomesticAirport}
              staffCode={staffCode}
              agentEmployeeType={agentEmployeeType}
              agentEmployeeCode={agentEmployeeCode}
              designation={designation}
              agencyDealershipName={agencyDealershipName}
              mealPreference={mealPreference}
              onBaseCity={setBaseCity}
              onNearestDomesticAirport={setNearestDomesticAirport}
              onStaffCode={setStaffCode}
              onAgentEmployeeType={setAgentEmployeeType}
              onAgentEmployeeCode={setAgentEmployeeCode}
              onDesignation={setDesignation}
              onAgencyDealershipName={setAgencyDealershipName}
              onMealPreference={setMealPreference}
            />
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
              {hasPassport ? "Submit Verified Details" : "Submit Traveller Details"}
            </Button>
          </form>
        )}
      </ReviewLayout>
    );
  }

  if (step === "FAMILY_REVIEW") {
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
              <section key={member.localId} className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
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
                  <div className="mt-5 rounded-2xl border border-slate-100 bg-slate-50 p-3 sm:p-4">
                    <h3 className="text-sm font-bold text-slate-900">Individual broadcast contact optional</h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500">If provided, this member can receive only their own details later. The head still receives all details.</p>
                    <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
                      <ContactInput icon={<Mail className="h-5 w-5" />} label="Member email" type="email" value={member.email} onChange={(value) => updateFamilyMember(index, { email: value })} />
                      <ContactInput icon={<Phone className="h-5 w-5" />} label="Member WhatsApp active number" type="tel" value={member.phone} onChange={(value) => updateFamilyMember(index, { phone: value })} />
                    </div>
                  </div>
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
            </section>
            );
          })}
          {!hasBlockedFamilyVerification ? (
            <>
              <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
                <h2 className="text-lg font-bold text-slate-900">Head of family contact</h2>
                <p className="mt-1 text-sm leading-6 text-slate-500">Provide WhatsApp active contact for the head of family. They will receive the full family packet later when WhatsApp broadcast is enabled.</p>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <ContactInput icon={<Mail className="h-5 w-5" />} label="Head email" type="email" value={headEmail} onChange={setHeadEmail} required />
                  <ContactInput icon={<Phone className="h-5 w-5" />} label="Head WhatsApp active number" type="tel" value={headPhone} onChange={setHeadPhone} required />
                </div>
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
                Submit Family Details
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

  if (step === "SUCCESS") {
    const name = flowMode === "family"
      ? `${familyMembers.length} family members`
      : (clientName || "your traveller details");
    return (
      <CenteredShell>
        <div
          role="status"
          aria-live="polite"
          className="w-full max-w-md rounded-2xl border border-slate-100 bg-white p-8 text-center shadow-xl shadow-slate-200/50"
        >
          <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-tr from-green-500 to-emerald-400 shadow-lg shadow-green-500/30">
            <CheckCircle2 className="h-10 w-10 text-white" aria-hidden="true" />
          </div>
          <h2 className="mb-3 text-3xl font-bold tracking-tight text-slate-900">Details Submitted</h2>
          <p className="mb-8 text-base leading-relaxed text-slate-500">
            Thank you. <span className="font-semibold text-slate-900">{name}</span> have been securely submitted to the <strong>{group.name}</strong> group.
          </p>
          <div className="rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm font-medium text-slate-500">You may now safely close this window.</div>
        </div>
      </CenteredShell>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 px-3 py-4 font-sans selection:bg-blue-100 selection:text-blue-900 sm:flex sm:flex-col sm:items-center sm:justify-center sm:px-4 sm:py-8 lg:py-12">
      <div className={`mx-auto w-full ${step === "METHOD_SELECT" && flowMode === "family" ? "max-w-5xl" : "max-w-lg"}`}>
        <UploadHeader groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
        <ErrorMessage message={uploadError} />
        <div className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-8">
          {step === "MODE_SELECT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h3 className="mb-2 text-xl font-bold text-slate-900">Who are you submitting for?</h3>
              <p className="mb-6 text-sm text-slate-500">Choose single passenger or family upload.</p>
              <div className="space-y-4">
                <ChoiceCard icon={<User className="h-6 w-6" />} title="Single" description="Submit travel details for one person." onClick={() => chooseMode("single")} />
                <ChoiceCard icon={<Users className="h-6 w-6" />} title="Family" description="Submit travel details for your family together." onClick={() => chooseMode("family")} />
              </div>
            </div>
          )}

          {step === "QUALIFIER_SELECT" && (
            <>
            <RelationQualifierStep
              path={qualifierPath}
              relationCode={qualifierRelationCode}
              options={group.qualifier_relation_options ?? []}
              isSaving={isSavingQualifier}
              onPathChange={(nextPath) => {
                setQualifierPath(nextPath);
                if (nextPath === "self") setQualifierRelationCode("");
                setUploadError(null);
              }}
              onRelationChange={setQualifierRelationCode}
              onContinue={saveQualifierChoice}
            />
            {!requiredField("relation_with_qualifier") && <Button type="button" variant="ghost" className="mt-4 h-11 w-full" onClick={() => {
              clearQualifierSelectionToken(token);
              setQualifierSelectionToken(null);
              setPersistedQualifierChoice(null);
              setQualifierPath(null);
              setQualifierRelationCode("");
              setFlowMode("single");
              setStep("METHOD_SELECT");
            }}>Continue without relationship details</Button>}
            </>
          )}

          {step === "FAMILY_SETUP" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <BackButton onClick={() => setStep("MODE_SELECT")} />
              <h3 className="mb-2 text-xl font-bold text-slate-900">Family Details</h3>
              <p className="mb-5 text-sm leading-6 text-slate-500 sm:mb-6">Enter every member first. Member email and phone are optional; head contact is required at final submit.</p>
              <form onSubmit={startFamilyUploads} className="space-y-4 sm:space-y-5">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">How many people?</span>
                  <Input
                    type="number"
                    min={2}
                    max={20}
                    value={familyCountInput}
                    onChange={(event) => handleFamilyCountInput(event.target.value)}
                    onBlur={normalizeFamilyCountInput}
                    inputMode="numeric"
                    className="h-12 rounded-xl border-slate-200 bg-slate-50 text-base tabular-nums shadow-sm focus-visible:bg-white"
                  />
                </label>
                <div className="max-h-none space-y-4 sm:max-h-[58vh] sm:overflow-y-auto sm:pr-1">
                  {familyMembers.map((member, index) => (
                    <div key={member.localId} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3 shadow-sm sm:p-4">
                      <p className="mb-3 text-sm font-bold text-slate-900">Member {index + 1}{index === 0 ? " • Head of family" : ""}</p>
                      <div className="grid min-w-0 gap-3">
                        <NameInput value={member.name} onChange={(value) => updateFamilyMember(index, { name: value })} placeholder="Full name" />
                        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                          <SelectInput label="Relation" value={member.relation} values={FAMILY_RELATIONS} onChange={(value) => updateFamilyMember(index, { relation: value })} disabled={index === 0} />
                          <SelectInput label="Gender" value={member.gender} values={GENDERS} onChange={(value) => updateFamilyMember(index, { gender: value })} />
                        </div>
                        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                          <ContactInput icon={<Mail className="h-5 w-5" />} label="Email optional" type="email" value={member.email} onChange={(value) => updateFamilyMember(index, { email: value })} />
                          <ContactInput icon={<Phone className="h-5 w-5" />} label="WhatsApp number optional" type="tel" value={member.phone} onChange={(value) => updateFamilyMember(index, { phone: value })} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <Button type="submit" size="lg" className="h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700">
                  Continue to Documents
                </Button>
              </form>
            </div>
          )}

          {step === "METHOD_SELECT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              {flowMode === "family" && activeFamilyMember ? (
                <div className="grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
                  <aside className="rounded-2xl border border-slate-100 bg-slate-50 p-3 sm:p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <h3 className="text-base font-bold text-slate-900">Family members</h3>
                      <button type="button" onClick={() => setStep("FAMILY_SETUP")} className="text-sm font-semibold text-blue-700">Edit</button>
                    </div>
                    <div className="space-y-2">
                      {familyMembers.map((member, index) => {
                        const isActive = index === activeFamilyIndex;
                        const isUploaded = Boolean(member.submission);
                        return (
                          <button
                            key={member.localId}
                            type="button"
                            onClick={() => selectFamilyMember(index)}
                            className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-3 text-left transition ${
                              isActive ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-200"
                            }`}
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-bold text-slate-950">{member.name}</span>
                              <span className="block truncate text-xs text-slate-500">{member.relation} • {member.gender}</span>
                            </span>
                            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                              isUploaded ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"
                            }`}>
                              {isUploaded ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    {familyMembers.every((member) => member.submission) && (
                      <Button type="button" className="mt-4 h-11 w-full" onClick={() => setStep("FAMILY_REVIEW")}>
                        Review family details
                      </Button>
                    )}
                  </aside>
                  <section className="rounded-2xl border border-slate-100 bg-white p-4">
                    <div className="mb-5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">Travel documents</p>
                      <h3 className="mt-1 text-xl font-bold text-slate-900">{activeFamilyMember.name}</h3>
                      <p className="mt-1 text-sm text-slate-500">Add the documents requested for this family member.</p>
                    </div>
                    <div className="space-y-4">
                      {selfieEnabled && !activeFamilyMember.submission && (
                        <VisaSelfieChoice
                          file={activeVisaSelfie}
                          allowCamera={uploadConfig.visa_photo_live_capture}
                          allowUpload={uploadConfig.visa_photo_upload}
                          required={selfieRequired}
                          onCameraClick={() => setStep("SELFIE_CAMERA")}
                          onUploadClick={() => setStep("SELFIE_UPLOAD")}
                        />
                      )}
                      {activeFamilyMember.submission ? (
                        <SavedPassportActions
                          onResume={() => setStep("FAMILY_REVIEW")}
                          onReplace={() => void replaceSavedPassport(activeFamilyIndex)}
                          isReplacing={isReplacingSavedPassport}
                        />
                      ) : documentChoices}
                    </div>
                  </section>
                </div>
              ) : (
                <>
                  <div className="mb-6">
                    <BackButton
                      onClick={() => setStep(
                        group.relation_with_qualifier_enabled
                          ? "QUALIFIER_SELECT"
                          : "MODE_SELECT",
                      )}
                    />
                    <div>
                      <h3 className="text-xl font-bold text-slate-900">Upload Method</h3>
                    </div>
                  </div>
                  <div className="space-y-4">
                    {selfieEnabled && !submission && (
                      <VisaSelfieChoice
                        file={activeVisaSelfie}
                          allowCamera={uploadConfig.visa_photo_live_capture}
                          allowUpload={uploadConfig.visa_photo_upload}
                          required={selfieRequired}
                        onCameraClick={() => setStep("SELFIE_CAMERA")}
                        onUploadClick={() => setStep("SELFIE_UPLOAD")}
                      />
                    )}
                    {submission ? (
                      <SavedPassportActions
                        onResume={() => setStep("REVIEW")}
                        onReplace={() => void replaceSavedPassport(null)}
                        isReplacing={isReplacingSavedPassport}
                      />
                    ) : documentChoices}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
