"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AxiosError, isAxiosError } from "axios";
import {
  AlertCircle,
  ArrowLeft,
  Camera,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Mail,
  MapPin,
  Phone,
  BadgeCheck,
  ImagePlus,
  User,
  Users,
  Utensils,
  X,
} from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { previousPassportIsoDate } from "@/lib/utils/passport-date";
import {
  formatPassportCountry,
  formatPassportNationality,
  isRecognizedPassportCountryCode,
} from "@/lib/utils/passport-country";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
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
  applyUploadReconciliation,
  createUploadRecoveryRecord,
  parseUploadRecoveryRecord,
  serializeUploadRecoveryRecord,
  uploadRecoveryTarget,
} from "../services/upload-recovery";
import {
  passportDocumentVerificationGate,
  type PassportDocumentVerificationGate,
} from "../services/passport-document-verification";
import {
  EXTRACTION_POLL_INITIAL_DELAY_MS,
  EXTRACTION_POLL_WINDOW_MS,
  isTransientExtractionPollError,
  nextExtractionPollDelay,
} from "./extraction-polling";
import { SmartCamera } from "./smart-camera";
import { VisaSelfieCamera } from "./visa-selfie-camera";
import { RelationQualifierStep } from "./relation-qualifier-step";
import { ProtectedUploadDocumentImage } from "./protected-upload-document-image";

interface UploadFlowProps {
  token: string;
}

type FlowMode = "single" | "family";
type Step =
  | "BOOTSTRAP"
  | "RECOVERY_ERROR"
  | "QUALIFIER_SELECT"
  | "MODE_SELECT"
  | "NAME_INPUT"
  | "FAMILY_SETUP"
  | "METHOD_SELECT"
  | "SELFIE_CAMERA"
  | "CAMERA"
  | "UPLOADING"
  | "REVIEW"
  | "FAMILY_REVIEW"
  | "SUBMITTING"
  | "SUCCESS";

interface FamilyMember {
  localId: string;
  name: string;
  relation: string;
  gender: string;
  email: string;
  phone: string;
  baseCity: string;
  nearestDomesticAirport: string;
  staffCode: string;
  mealPreference: string;
  submission: PassportSubmission | null;
  reviewFields: Record<string, string>;
  visaSelfie: File | null;
  uploadIdempotencyKey: string;
  extractionNotice: string | null;
  canRetryExtraction: boolean;
}

interface PassportDocumentBundle {
  front: File | null;
  back: File | null;
  frontSource: "camera" | "file" | null;
  backSource: "camera" | "file" | null;
}

interface ExtractionWaitResult {
  submission: PassportSubmission;
  notice: string | null;
  retryAllowed: boolean;
}

const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "issuing_country",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const;

const REQUIRED_REVIEW_FIELDS = REVIEW_FIELDS.filter((field) => field !== "date_of_issue");
const RELATIONS = ["Head", "Spouse", "Son", "Daughter", "Father", "Mother", "Brother", "Sister", "Other"];
const GENDERS = ["Male", "Female", "Other", "Prefer not to say"];
const PASSPORT_IMAGE_ACCEPT = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".heic",
  ".heif",
  ".avif",
  ".bmp",
  ".tif",
  ".tiff",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/bmp",
  "image/tiff",
].join(",");

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
  const [mealPreference, setMealPreference] = useState("");
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
  const [documentBundle, setDocumentBundle] = useState<PassportDocumentBundle>(() => emptyDocumentBundle());
  const [scannerPageSide, setScannerPageSide] = useState<"front" | "back">("front");
  const mountedRef = useRef(false);
  const operationInFlightRef = useRef(false);
  const requestControllerRef = useRef<AbortController | null>(null);
  const scanAgainInFlightRef = useRef(false);
  const qualifierSaveInFlightRef = useRef(false);
  const initializedGroupTokenRef = useRef<string | null>(null);
  const resumeSubmissionRef = useRef<PassportSubmission | null>(null);
  const resumeInFlightRef = useRef<string | null>(null);
  const departureCities = group?.departure_cities ?? [];
  const airportEnabled = Boolean(group?.nearest_international_airport_enabled || departureCities.length > 0);
  const baseCityEnabled = group?.base_city_enabled ?? false;
  const staffCodeEnabled = group?.staff_code_enabled ?? false;
  const mealPreferenceEnabled = group?.meal_preference_enabled ?? false;
  const selfieRequired = group?.require_selfie ?? false;
  const allowFilesFromDevice = group?.allow_files_from_device ?? true;
  const askNearestDomesticAirport = group?.ask_nearest_domestic_airport ?? false;
  const groupId = group?.id;
  const relationWithQualifierEnabled =
    group?.relation_with_qualifier_enabled ?? false;
  const activeFamilyMember = familyMembers[activeFamilyIndex] ?? null;
  const activeVisaSelfie = flowMode === "family" ? activeFamilyMember?.visaSelfie ?? null : visaSelfie;
  const hasBlockedFamilyVerification = familyMembers.some((member) => (
    member.submission === null
    || !passportDocumentVerificationGate(member.submission).accepted
  ));
  const hasActiveProgress = step !== "SUCCESS" && (
    submission !== null
    || familyMembers.some((member) => member.submission !== null)
    || qualifierSelectionToken !== null
    || clientName.trim().length > 0
    || !["BOOTSTRAP", "QUALIFIER_SELECT", "MODE_SELECT"].includes(step)
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
    void (async () => {
      // Yield once so all initialization state changes happen from the
      // external session/API synchronization callback, not synchronously in
      // the effect body.
      await Promise.resolve();
      if (cancelled) return;

      const storedRecovery = readUploadRecoveryRecord(token);
      const recovery = storedRecovery
        ?? createUploadRecoveryRecord(createIdempotencyKey());
      setSingleUploadIdempotencyKey(recovery.idempotencyKey);
      if (!storedRecovery) writeUploadRecoveryRecord(token, recovery);

      const restoreSubmission = async (submissionId: string) => {
        try {
          const savedSubmission = await uploadApi.getUploadStatus(
            token,
            submissionId,
            recovery.idempotencyKey,
          );
          if (cancelled) return;
          reportPublicFlowOnce("recovery_succeeded");
          writeUploadRecoveryRecord(
            token,
            createUploadRecoveryRecord(recovery.idempotencyKey, savedSubmission.id),
          );
          setSubmission(savedSubmission);
          setClientName(savedSubmission.client_name);
          if (isClientSubmissionComplete(savedSubmission)) {
            setStep("SUCCESS");
            return;
          }
          if (isExtractionTerminal(savedSubmission)) {
            setReviewFields(getInitialReviewFields(savedSubmission.extracted_fields));
            setExtractionNotice(extractionNoticeFor(savedSubmission));
            setCanRetryExtraction(canRetryExtractionFor(savedSubmission));
            setStep("REVIEW");
            return;
          }
          setProcessingProgress(savedSubmission.processing_progress ?? 0.05);
          setProcessingStage(stageLabel(
            savedSubmission.processing_stage
            ?? savedSubmission.processing_job_status
            ?? "queued",
          ));
          resumeSubmissionRef.current = savedSubmission;
          setResumeSubmissionId(savedSubmission.id);
          setStep("UPLOADING");
        } catch (restoreError: unknown) {
          if (cancelled) return;
          reportPublicFlowOnce("recovery_missed");
          if (isMissingSavedSubmissionError(restoreError)) {
            const replacement = createUploadRecoveryRecord(createIdempotencyKey());
            writeUploadRecoveryRecord(token, replacement);
            setSingleUploadIdempotencyKey(replacement.idempotencyKey);
            setUploadError(
              "The previous saved upload is no longer available. Please start a new upload.",
            );
            if (relationWithQualifierEnabled) {
              clearQualifierSelectionToken(token);
              setQualifierSelectionToken(null);
              setPersistedQualifierChoice(null);
              setStep("QUALIFIER_SELECT");
            } else {
              setStep("MODE_SELECT");
            }
            return;
          }
          setUploadError(errorMessage(
            restoreError,
            "Your saved passport upload could not be reached. Retry reconnecting; a new upload has not been started.",
          ));
          setStep("RECOVERY_ERROR");
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
          if (cancelled) return;
          const reconciledRecovery = applyUploadReconciliation(
            recovery,
            reconciled.submission_id,
          );
          if (reconciledRecovery.submissionId) {
            writeUploadRecoveryRecord(token, reconciledRecovery);
            setFlowMode("single");
            await restoreSubmission(reconciledRecovery.submissionId);
            return;
          }
          reportPublicFlowOnce("recovery_missed");
        } catch (reconciliationError: unknown) {
          if (cancelled) return;
          reportPublicFlowOnce("recovery_missed");
          setUploadError(errorMessage(
            reconciliationError,
            "We could not check whether your previous upload was saved. Retry reconnecting before selecting the passport files again.",
          ));
          setStep("RECOVERY_ERROR");
          return;
        }
      }

      // A durable submission is already bound to this browser's private upload
      // credential. Restore it before consulting the short-lived qualifier
      // selection token so refresh/back navigation cannot create a second
      // relationship choice for an upload that was safely persisted.
      if (recovery.submissionId) {
        setFlowMode("single");
        await restoreSubmission(recovery.submissionId);
        return;
      }

      if (!relationWithQualifierEnabled) {
        setStep("MODE_SELECT");
        return;
      }

      setFlowMode("single");
      const storedToken = readQualifierSelectionToken(token);
      if (!storedToken) {
        setStep("QUALIFIER_SELECT");
        return;
      }

      let selection: Awaited<
        ReturnType<typeof uploadLinksApi.getQualifierSelection>
      >;
      try {
        selection = await uploadLinksApi.getQualifierSelection(token, storedToken);
      } catch (restoreError: unknown) {
        if (cancelled) return;
        if (isPermanentQualifierRestoreError(restoreError)) {
          clearQualifierSelectionToken(token);
          setQualifierSelectionToken(null);
          setPersistedQualifierChoice(null);
          setUploadError(
            "Your previous relationship choice is no longer available. Please choose again.",
          );
          setStep("QUALIFIER_SELECT");
          return;
        }
        setQualifierSelectionToken(storedToken);
        setUploadError(errorMessage(
          restoreError,
          "Your saved relationship choice could not be reached. Retry reconnecting; it has not been discarded.",
        ));
        setStep("RECOVERY_ERROR");
        return;
      }
      if (cancelled) return;
      if (selection.status === "expired") {
        clearQualifierSelectionToken(token);
        setQualifierSelectionToken(null);
        setPersistedQualifierChoice(null);
        setUploadError("Your previous relationship choice expired. Please choose again.");
        setStep("QUALIFIER_SELECT");
        return;
      }

      setQualifierSelectionToken(storedToken);
      setQualifierPath(selection.is_self ? "self" : "relation");
      setQualifierRelationCode(selection.relation_code ?? "");
      setPersistedQualifierChoice(qualifierChoiceKey(
        selection.is_self ? "self" : "relation",
        selection.relation_code ?? "",
      ));

      if (selection.status === "active" || !selection.submission_id) {
        setStep("NAME_INPUT");
        return;
      }

      writeUploadRecoveryRecord(
        token,
        createUploadRecoveryRecord(recovery.idempotencyKey, selection.submission_id),
      );
      await restoreSubmission(selection.submission_id);
    })();

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
      setStep("NAME_INPUT");
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
      setStep("NAME_INPUT");
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
    setUploadError(null);
  };

  const chooseMode = (mode: FlowMode) => {
    setFlowMode(mode);
    setUploadError(null);
    setStep(mode === "single" ? "NAME_INPUT" : "FAMILY_SETUP");
  };

  const handleNameSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (clientName.trim().length > 1) setStep("METHOD_SELECT");
  };

  const updateFamilyCount = (count: number) => {
    const safeCount = Math.max(2, Math.min(20, count));
    setFamilyCountInput(String(safeCount));
    setFamilyMembers((current) => {
      const next = [...current];
      while (next.length < safeCount) next.push(createFamilyMember(next.length));
      return next.slice(0, safeCount).map((member, index) => ({
        ...member,
        relation: index === 0 ? "Head" : member.relation,
      }));
    });
  };

  const handleFamilyCountInput = (value: string) => {
    if (!/^\d*$/.test(value)) return;
    setFamilyCountInput(value);
    if (!value) return;
    const count = Number(value);
    if (Number.isNaN(count)) return;
    if (count >= 2 && count <= 20) {
      setFamilyMembers((current) => {
        const next = [...current];
        while (next.length < count) next.push(createFamilyMember(next.length));
        return next.slice(0, count).map((member, index) => ({
          ...member,
          relation: index === 0 ? "Head" : member.relation,
        }));
      });
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
    if (!documentBundle.front) {
      setUploadError("Upload the passport front page before continuing.");
      return;
    }
    if (!documentBundle.back) {
      setUploadError("Upload the passport back page before continuing.");
      return;
    }
    if (selfieRequired && !activeVisaSelfie) {
      setUploadError("Capture the required Visa Photo before continuing.");
      return;
    }
    const acquisitionMode = documentBundle.frontSource === "camera"
      && documentBundle.backSource === "camera"
      ? "camera"
      : "file";
    if (!allowFilesFromDevice && acquisitionMode !== "camera") {
      setUploadError("This group requires both passport pages to be captured with the live scanner.");
      return;
    }
    await processUpload(
      documentBundle.front,
      documentBundle.back,
      acquisitionMode,
      activeVisaSelfie,
    );
  };

  const handleCameraCapture = (file: File) => {
    const capturedSide = scannerPageSide;
    setDocumentBundle((current) => ({
      ...current,
      [capturedSide]: file,
      [`${capturedSide}Source`]: "camera",
    }));
    setUploadError(null);
    if (capturedSide === "front" && !documentBundle.back) {
      setScannerPageSide("back");
      return;
    }
    setStep("METHOD_SELECT");
  };

  const openPassportScanner = (pageSide: "front" | "back") => {
    setScannerPageSide(pageSide);
    setUploadError(null);
    setStep("CAMERA");
  };

  const handleSelfieCapture = (file: File) => {
    setUploadError(null);
    if (flowMode === "family") {
      setFamilyMembers((current) => current.map((member, index) => (
        index === activeFamilyIndex ? { ...member, visaSelfie: file } : member
      )));
    } else {
      setVisaSelfie(file);
    }
    setStep("METHOD_SELECT");
  };

  const processUpload = async (
    file: File,
    passportBackFile: File,
    acquisitionMode: "camera" | "file",
    passportPhotoFile?: File | null,
  ) => {
    if (operationInFlightRef.current) return;
    const uploadName = flowMode === "family" ? activeFamilyMember?.name : clientName;
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
      const normalized = await normalizePassportFile(file);
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
        file: normalized.file,
        passportPhotoFile,
        passportBackFile,
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
      setSubmission(persisted);
      setProcessingProgress(persisted.processing_progress ?? 0.05);
      setProcessingStage("Passport pages saved. Reading available details for review.");
      const waitResult = isExtractionTerminal(persisted)
        ? {
          submission: persisted,
          notice: extractionNoticeFor(persisted),
          retryAllowed: canRetryExtractionFor(persisted),
        }
        : await waitForExtraction(
          persisted,
          uploadIdempotencyKey,
          controller.signal,
        );
      const completed = waitResult.submission;
      if (!mountedRef.current || controller.signal.aborted) return;
      setDocumentBundle(emptyDocumentBundle());

      if (familyIndex !== null) {
        const fields = getInitialReviewFields(completed.extracted_fields);
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
      setReviewFields(getInitialReviewFields(completed.extracted_fields));
      setStep("REVIEW");
    } catch (error: unknown) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setIsPreparingFile(false);
      setProcessingProgress(null);
      setProcessingStage("Uploading securely");
      if (persisted) {
        const notice = "Your passport pages were saved, but automatic reading could not be confirmed. Enter the details manually or retry reading the stored image.";
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
          setReviewFields(getInitialReviewFields(persisted.extracted_fields));
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
  ): Promise<ExtractionWaitResult> => {
    let current = initial;
    if (mountedRef.current) {
      setSubmission(current);
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
        setSubmission(current);
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
    if (!verificationGate.accepted) {
      setUploadError(verificationGate.message);
      return;
    }
    if (hasMissingRequiredFields(reviewFields)) {
      setUploadError("Please fill all required passport fields before submitting.");
      return;
    }
    if (!hasValidReviewDates(reviewFields)) {
      setUploadError("Enter valid passport dates in DD/MM/YYYY format. Check that birth, issue, and expiry are chronological and no entered birth or issue date is in the future.");
      return;
    }
    if (airportEnabled && !departureCity) {
      setUploadError("Please select your nearest international airport before submitting.");
      return;
    }
    if (baseCityEnabled && !baseCity.trim()) {
      setUploadError("Please enter your base city before submitting.");
      return;
    }
    if (askNearestDomesticAirport && !nearestDomesticAirport.trim()) {
      setUploadError("Please enter your nearest domestic airport before submitting.");
      return;
    }
    if (staffCodeEnabled && !staffCode.trim()) {
      setUploadError("Please enter your staff code before submitting.");
      return;
    }
    if (mealPreferenceEnabled && !mealPreference) {
      setUploadError("Please select a meal preference before submitting.");
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
        meal_preference: mealPreference || null,
        submission_mode: "single",
      });
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
      && !passportDocumentVerificationGate(member.submission).accepted
    ));
    if (blockedVerification?.submission) {
      setUploadError(
        `${blockedVerification.name || "A family member"}: ${
          passportDocumentVerificationGate(blockedVerification.submission).message
        }`,
      );
      return;
    }
    if (airportEnabled && !departureCity) {
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
      hasMissingRequiredFields(member.reviewFields) || !hasValidReviewDates(member.reviewFields)
    ));
    if (invalidReview) {
      setUploadError(`Fill all passport fields for ${invalidReview.name}.`);
      return;
    }
    const missingConfiguredField = familyMembers.find((member) => (
      (baseCityEnabled && !member.baseCity.trim())
      || (askNearestDomesticAirport && !member.nearestDomesticAirport.trim())
      || (staffCodeEnabled && !member.staffCode.trim())
      || (mealPreferenceEnabled && !member.mealPreference)
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
          meal_preference: member.mealPreference || null,
          submission_mode: "family",
          family_group_id: familyGroupId,
          family_member_index: index,
          family_relation: member.relation,
          family_gender: member.gender,
          family_head_name: familyMembers[0]?.name || member.name,
          family_head_email: headEmail,
          family_head_phone: headPhone,
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

  if (step === "CAMERA") {
    return (
      <SmartCamera
        key={scannerPageSide}
        pageSide={scannerPageSide}
        allowFileFallback={allowFilesFromDevice}
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
        onCapture={handleSelfieCapture}
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

  if (isPreparingFile) {
    return <ProcessingScreen title="Preparing Passport Image" description="Straightening the capture and optimizing it before secure upload." />;
  }

  if (step === "UPLOADING") {
    return (
      <ProcessingScreen
        title="Processing Passport"
        description={processingStage}
        progress={processingProgress}
      />
    );
  }

  if (step === "SUBMITTING") {
    return <ProcessingScreen title="Submitting Reviewed Details" description="Sending the verified passport information to your travel agency." />;
  }

  if (step === "REVIEW" && submission) {
    const verificationGate = passportDocumentVerificationGate(submission);
    return (
      <ReviewLayout
        title={verificationGate.accepted
          ? "Verify Passport Details"
          : "Passport Verification Required"}
        description={verificationGate.accepted
          ? "Please check every field carefully before submitting."
          : "The saved upload must be verified before any passport details can be reviewed or submitted."}
        image={(
          <ProtectedUploadDocumentImage
            token={token}
            submissionId={submission.id}
            uploadSessionId={singleUploadIdempotencyKey}
            documentType="front"
            alt="Uploaded passport front"
            className="block h-auto w-full"
          />
        )}
        photoImage={submission.passport_photo_s3_key
          ? (
            <ProtectedUploadDocumentImage
              token={token}
              submissionId={submission.id}
              uploadSessionId={singleUploadIdempotencyKey}
              documentType="photo"
              alt="Uploaded Visa Photo"
              className="block h-auto w-full"
            />
          )
          : null}
        backImage={submission.passport_back_s3_key
          ? (
            <ProtectedUploadDocumentImage
              token={token}
              submissionId={submission.id}
              uploadSessionId={singleUploadIdempotencyKey}
              documentType="back"
              alt="Uploaded passport back"
              className="block h-auto w-full"
            />
          )
          : null}
        fields={submission.extracted_fields}
        onBack={handleBackToUploadMethods}
      >
        {!verificationGate.accepted ? (
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
            <ReviewWarning />
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
            <ReviewFields fields={reviewFields} onChange={handleReviewFieldChange} />
            <ContactSection
              email={clientEmail}
              phone={clientPhone}
              departureCity={departureCity}
              departureCities={departureCities}
              onEmail={setClientEmail}
              onPhone={setClientPhone}
              onDepartureCity={setDepartureCity}
              title="Contact Details"
              emailRequired
              phoneRequired
            />
            <ConfiguredClientFields
              baseCityEnabled={baseCityEnabled}
              askNearestDomesticAirport={askNearestDomesticAirport}
              staffCodeEnabled={staffCodeEnabled}
              mealPreferenceEnabled={mealPreferenceEnabled}
              baseCity={baseCity}
              nearestDomesticAirport={nearestDomesticAirport}
              staffCode={staffCode}
              mealPreference={mealPreference}
              onBaseCity={setBaseCity}
              onNearestDomesticAirport={setNearestDomesticAirport}
              onStaffCode={setStaffCode}
              onMealPreference={setMealPreference}
            />
            <Button
              type="submit"
              size="lg"
              disabled={isScanningAgain}
              className="mt-6 h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
            >
              Submit Verified Details
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
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Review Family Passport Details</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600">Check all family member details together before final submission.</p>
          </div>
          <ErrorMessage message={uploadError} />
          {familyMembers.map((member, index) => {
            const verificationGate = member.submission
              ? passportDocumentVerificationGate(member.submission)
              : null;
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
                  {member.submission ? "Replace passport" : "Upload passport"}
                </button>
              </div>
              <div className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
                <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
                  {member.submission ? (
                    <div className="relative w-full">
                      {member.submission.passport_photo_s3_key && (
                        <ProtectedUploadDocumentImage
                          token={token}
                          submissionId={member.submission.id}
                          uploadSessionId={member.uploadIdempotencyKey}
                          documentType="photo"
                          alt={`${member.name} Visa Photo`}
                          className="block h-auto w-full border-b border-slate-200"
                        />
                      )}
                      <div className="relative">
                        <ProtectedUploadDocumentImage
                          token={token}
                          submissionId={member.submission.id}
                          uploadSessionId={member.uploadIdempotencyKey}
                          documentType="front"
                          alt={`${member.name} passport front`}
                          className="block h-auto w-full"
                        />
                        <PassportRoiOverlays fields={member.submission.extracted_fields} />
                      </div>
                      {member.submission.passport_back_s3_key && (
                        <ProtectedUploadDocumentImage
                          token={token}
                          submissionId={member.submission.id}
                          uploadSessionId={member.uploadIdempotencyKey}
                          documentType="back"
                          alt={`${member.name} passport back`}
                          className="block h-auto w-full border-t border-slate-200"
                        />
                      )}
                    </div>
                  ) : (
                    <div className="flex min-h-72 items-center justify-center text-sm text-slate-400">Passport preview unavailable</div>
                  )}
                </div>
                {!verificationGate ? (
                  <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium leading-6 text-amber-950">
                    Upload and verify this member&apos;s passport before reviewing any details.
                  </div>
                ) : !verificationGate.accepted ? (
                  <DocumentVerificationBlock
                    gate={verificationGate}
                    onRetry={() => void handleFamilyScanAgain(index)}
                    onReplace={() => void replaceSavedPassport(index)}
                    isRetrying={isScanningAgain}
                    isReplacing={isReplacingSavedPassport}
                  />
                ) : (
                  <div>
                    <ReviewWarning />
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
                    <ReviewFields fields={member.reviewFields} onChange={(key, value) => handleFamilyReviewFieldChange(index, key, value)} />
                  </div>
                )}
              </div>
              {verificationGate?.accepted && (
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
                    baseCityEnabled={baseCityEnabled}
                    askNearestDomesticAirport={askNearestDomesticAirport}
                    staffCodeEnabled={staffCodeEnabled}
                    mealPreferenceEnabled={mealPreferenceEnabled}
                    baseCity={member.baseCity}
                    nearestDomesticAirport={member.nearestDomesticAirport}
                    staffCode={member.staffCode}
                    mealPreference={member.mealPreference}
                    onBaseCity={(value) => updateFamilyMember(index, { baseCity: value })}
                    onNearestDomesticAirport={(value) => updateFamilyMember(index, { nearestDomesticAirport: value })}
                    onStaffCode={(value) => updateFamilyMember(index, { staffCode: value })}
                    onMealPreference={(value) => updateFamilyMember(index, { mealPreference: value })}
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
                  <DepartureCitySelect value={departureCity} cities={departureCities} onChange={setDepartureCity} className="mt-4" />
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
    const name = flowMode === "family" ? `${familyMembers.length} family members` : clientName;
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
        <UploadHeader groupName={group.name} />
        <ErrorMessage message={uploadError} />
        <div className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-8">
          {step === "MODE_SELECT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h3 className="mb-2 text-xl font-bold text-slate-900">Who are you submitting for?</h3>
              <p className="mb-6 text-sm text-slate-500">Choose single passenger or family upload.</p>
              <div className="space-y-4">
                <ChoiceCard icon={<User className="h-6 w-6" />} title="Single" description="Upload passport for one person." onClick={() => chooseMode("single")} />
                <ChoiceCard icon={<Users className="h-6 w-6" />} title="Family" description="Upload passports for multiple family members together." onClick={() => chooseMode("family")} />
              </div>
            </div>
          )}

          {step === "QUALIFIER_SELECT" && (
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
          )}

          {step === "NAME_INPUT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <BackButton
                onClick={() => setStep(
                  group.relation_with_qualifier_enabled
                    ? "QUALIFIER_SELECT"
                    : "MODE_SELECT",
                )}
              />
              <h3 className="mb-2 text-xl font-bold text-slate-900">Who is uploading?</h3>
              <p className="mb-6 text-sm text-slate-500">Enter the full name as it appears on the passport.</p>
              <form onSubmit={handleNameSubmit} className="space-y-6">
                <NameInput value={clientName} onChange={setClientName} autoFocus />
                <Button type="submit" size="lg" className="h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700" disabled={clientName.trim().length < 2}>
                  Continue <ChevronRight className="ml-1 h-5 w-5" />
                </Button>
              </form>
            </div>
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
                          <SelectInput label="Relation" value={member.relation} values={RELATIONS} onChange={(value) => updateFamilyMember(index, { relation: value })} disabled={index === 0} />
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
                  Continue to Passport Uploads
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
                        Review all passports
                      </Button>
                    )}
                  </aside>
                  <section className="rounded-2xl border border-slate-100 bg-white p-4">
                    <div className="mb-5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">Upload passport</p>
                      <h3 className="mt-1 text-xl font-bold text-slate-900">{activeFamilyMember.name}</h3>
                      <p className="mt-1 text-sm text-slate-500">Choose how you want to upload this member&apos;s passport.</p>
                    </div>
                    <div className="space-y-4">
                      {selfieRequired && (
                        <VisaSelfieChoice
                          file={activeVisaSelfie}
                          onClick={() => setStep("SELFIE_CAMERA")}
                        />
                      )}
                      {activeFamilyMember.submission ? (
                        <SavedPassportActions
                          onResume={() => setStep("FAMILY_REVIEW")}
                          onReplace={() => void replaceSavedPassport(activeFamilyIndex)}
                          isReplacing={isReplacingSavedPassport}
                        />
                      ) : (
                        <PassportUploadSection allowFilesFromDevice={allowFilesFromDevice}>
                          <PassportDocumentBundlePanel
                            bundle={documentBundle}
                            allowFilesFromDevice={allowFilesFromDevice}
                            onChange={setDocumentBundle}
                            onScan={openPassportScanner}
                            onUpload={handleBundleUpload}
                          />
                        </PassportUploadSection>
                      )}
                    </div>
                  </section>
                </div>
              ) : (
                <>
                  <div className="mb-6 flex items-center justify-between gap-4">
                    <div>
                      <h3 className="text-xl font-bold text-slate-900">Upload Method</h3>
                    </div>
                    <button onClick={() => setStep("NAME_INPUT")} className="text-sm font-medium text-blue-600 hover:text-blue-700 hover:underline">
                      Edit Name
                    </button>
                  </div>
                  <div className="space-y-4">
                    {selfieRequired && <VisaSelfieChoice file={activeVisaSelfie} onClick={() => setStep("SELFIE_CAMERA")} />}
                    {submission ? (
                      <SavedPassportActions
                        onResume={() => setStep("REVIEW")}
                        onReplace={() => void replaceSavedPassport(null)}
                        isReplacing={isReplacingSavedPassport}
                      />
                    ) : (
                      <PassportUploadSection allowFilesFromDevice={allowFilesFromDevice}>
                        <PassportDocumentBundlePanel
                          bundle={documentBundle}
                          allowFilesFromDevice={allowFilesFromDevice}
                          onChange={setDocumentBundle}
                          onScan={openPassportScanner}
                          onUpload={handleBundleUpload}
                        />
                      </PassportUploadSection>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
        <p className="mt-5 text-center text-xs font-medium text-slate-400 sm:mt-8">Protected by Enterprise-grade Encryption • End-to-End Secure</p>
      </div>
    </div>
  );
}

function createFamilyMember(index: number): FamilyMember {
  return {
    localId: typeof crypto !== "undefined" ? crypto.randomUUID() : `${Date.now()}-${index}`,
    name: "",
    relation: index === 0 ? "Head" : "",
    gender: "",
    email: "",
    phone: "",
    baseCity: "",
    nearestDomesticAirport: "",
    staffCode: "",
    mealPreference: "",
    submission: null,
    reviewFields: {},
    visaSelfie: null,
    uploadIdempotencyKey: createIdempotencyKey(),
    extractionNotice: null,
    canRetryExtraction: false,
  };
}

function createFamilyMembers(count: number) {
  return Array.from({ length: count }, (_, index) => createFamilyMember(index));
}

function emptyDocumentBundle(): PassportDocumentBundle {
  return {
    front: null,
    back: null,
    frontSource: null,
    backSource: null,
  };
}

function isClientSubmissionComplete(submission: PassportSubmission) {
  return [
    "submitted",
    "ai_approved",
    "needs_review",
    "staff_approved",
  ].includes(submission.status);
}

function uploadRecoveryStorageKey(groupToken: string) {
  return `gct:upload-recovery:${groupToken}`;
}

function readUploadRecoveryRecord(groupToken: string) {
  try {
    return parseUploadRecoveryRecord(
      window.sessionStorage.getItem(uploadRecoveryStorageKey(groupToken)),
    );
  } catch {
    return null;
  }
}

function writeUploadRecoveryRecord(
  groupToken: string,
  record: ReturnType<typeof createUploadRecoveryRecord>,
) {
  try {
    window.sessionStorage.setItem(
      uploadRecoveryStorageKey(groupToken),
      serializeUploadRecoveryRecord(record),
    );
  } catch {
    // Recovery storage is optional in privacy-restricted in-app browsers.
    // Backend idempotency still protects the active in-memory attempt.
  }
}

function qualifierStorageKey(groupToken: string) {
  return `gct:qualifier-selection:${groupToken}`;
}

function readQualifierSelectionToken(groupToken: string) {
  try {
    return window.sessionStorage.getItem(qualifierStorageKey(groupToken));
  } catch {
    return null;
  }
}

function writeQualifierSelectionToken(groupToken: string, selectionToken: string) {
  try {
    window.sessionStorage.setItem(
      qualifierStorageKey(groupToken),
      selectionToken,
    );
  } catch {
    // Session storage is an optional recovery aid. The in-memory bearer token
    // remains sufficient for the current upload attempt.
  }
}

function clearQualifierSelectionToken(groupToken: string) {
  try {
    window.sessionStorage.removeItem(qualifierStorageKey(groupToken));
  } catch {
    // Storage may be unavailable in privacy-restricted in-app browsers.
  }
}

function isPermanentQualifierRestoreError(error: unknown) {
  if (!isAxiosError(error)) return false;
  return [400, 401, 403, 404, 410, 422].includes(error.response?.status ?? 0);
}

function isMissingSavedSubmissionError(error: unknown) {
  if (!isAxiosError(error)) return false;
  return [404, 410].includes(error.response?.status ?? 0);
}

function UploadHeader({ groupName }: { groupName: string }) {
  return (
    <div className="mb-5 text-center sm:mb-8 lg:mb-10">
      <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 shadow-lg shadow-blue-600/30 sm:mb-6 sm:h-14 sm:w-14">
        <Users className="h-7 w-7 text-white" />
      </div>
      <h1 className="mb-2 text-2xl font-extrabold tracking-tight text-slate-900 sm:mb-3 sm:text-3xl">Upload Passport</h1>
      <p className="mx-auto max-w-md text-sm leading-relaxed text-slate-500 sm:text-base">Your travel agency has requested passport details for</p>
      <div className="mt-2 inline-flex max-w-full rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-600">
        <span className="truncate">{groupName}</span>
      </div>
    </div>
  );
}

function ChoiceCard({ icon, title, description, onClick }: { icon: ReactNode; title: string; description: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group flex w-full items-start gap-3 rounded-2xl border-2 border-slate-100 bg-white p-4 text-left shadow-sm transition-all active:scale-[0.99] hover:border-blue-600 hover:bg-blue-50/50 hover:shadow-md sm:gap-4 sm:p-5">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600 transition-colors group-hover:bg-blue-600 group-hover:text-white sm:h-12 sm:w-12">{icon}</div>
      <div className="min-w-0">
        <h4 className="text-base font-bold text-slate-900 transition-colors group-hover:text-blue-900">{title}</h4>
        <p className="mt-1 text-sm leading-5 text-slate-500">{description}</p>
      </div>
    </button>
  );
}

function VisaSelfieChoice({ file, onClick }: { file: File | null; onClick: () => void }) {
  return (
    <div className="relative">
      <ChoiceCard
        icon={file ? <CheckCircle2 className="h-6 w-6" /> : <User className="h-6 w-6" />}
        title={file ? "Visa Photo ready" : "Capture Visa Photo"}
        description={file
          ? "Original Visa Photo captured after live checks. Tap to retake it."
          : "Required. Use a plain white or off-white wall; capture unlocks when photo checks pass."}
        onClick={onClick}
      />
      <span className={`pointer-events-none absolute right-3 top-3 rounded-full px-2.5 py-1 text-[11px] font-bold ${file ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}`}>
        {file ? "Completed" : "Required"}
      </span>
    </div>
  );
}

function PassportUploadSection({
  children,
  allowFilesFromDevice,
}: {
  children: ReactNode;
  allowFilesFromDevice: boolean;
}) {
  return (
    <details className="group overflow-hidden rounded-2xl border-2 border-slate-100 bg-white shadow-sm" open>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 marker:hidden sm:p-5">
        <div>
          <h4 className="text-base font-bold text-slate-900">Passport</h4>
          <p className="mt-1 text-sm text-slate-500">
            {allowFilesFromDevice
              ? "Scan both passport pages live or choose existing images from this device."
              : "Live scanning is mandatory for both passport pages in this group."}
          </p>
        </div>
        <ChevronRight className="h-5 w-5 shrink-0 text-slate-400 transition-transform group-open:rotate-90" />
      </summary>
      <div className="border-t border-slate-100 p-4 pt-4 sm:p-5">
        <div className="space-y-4">{children}</div>
      </div>
    </details>
  );
}

function PassportDocumentBundlePanel({
  bundle,
  allowFilesFromDevice,
  onChange,
  onScan,
  onUpload,
}: {
  bundle: PassportDocumentBundle;
  allowFilesFromDevice: boolean;
  onChange: (bundle: PassportDocumentBundle) => void;
  onScan: (pageSide: "front" | "back") => void;
  onUpload: () => void;
}) {
  const updateFile = (pageSide: "front" | "back", file: File | null) => {
    onChange(pageSide === "front"
      ? { ...bundle, front: file, frontSource: file ? "file" : null }
      : { ...bundle, back: file, backSource: file ? "file" : null });
  };
  const readyPageCount = Number(Boolean(bundle.front)) + Number(Boolean(bundle.back));

  return (
    <div className="rounded-3xl border border-slate-200 bg-gradient-to-b from-white to-slate-50/70 p-3 shadow-sm sm:p-5">
      <div className="mb-5 flex items-start gap-3 px-1">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-700 ring-1 ring-blue-100 sm:h-12 sm:w-12">
          <Camera className="h-6 w-6" />
        </div>
        <div className="min-w-0">
          <h4 className="text-base font-bold text-slate-900">Capture both passport pages</h4>
          <p className="mt-1 text-sm leading-5 text-slate-500">
            Add a clear front and back image. We will read the details after both pages are saved.
          </p>
        </div>
      </div>

      {!allowFilesFromDevice && (
        <div role="status" className="mb-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm font-medium leading-5 text-blue-900">
          Live scanning is required. Gallery and file-picker options are disabled for this group.
        </div>
      )}

      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))" }}
      >
        <PassportPageCaptureControl
          pageSide="front"
          file={bundle.front}
          source={bundle.frontSource}
          allowFilesFromDevice={allowFilesFromDevice}
          onScan={() => onScan("front")}
          onFileChange={(file) => updateFile("front", file)}
        />
        <PassportPageCaptureControl
          pageSide="back"
          file={bundle.back}
          source={bundle.backSource}
          allowFilesFromDevice={allowFilesFromDevice}
          onScan={() => onScan("back")}
          onFileChange={(file) => updateFile("back", file)}
        />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 px-1 text-xs">
        <span className="font-medium text-slate-500" aria-live="polite">
          {readyPageCount} of 2 pages ready
        </span>
        <span className={readyPageCount === 2 ? "font-semibold text-emerald-700" : "text-slate-400"}>
          {readyPageCount === 2 ? "Ready to extract" : "Both pages required"}
        </span>
      </div>
      <Button
        type="button"
        className="mt-3 h-12 w-full rounded-xl bg-blue-600 font-semibold shadow-lg shadow-blue-600/15 hover:bg-blue-700"
        onClick={onUpload}
        disabled={!bundle.front || !bundle.back}
      >
        <BadgeCheck className="h-5 w-5" aria-hidden="true" />
        Save pages &amp; extract details
      </Button>
      <p className="mt-3 px-1 text-center text-xs leading-5 text-slate-400">
        Reading usually takes about 30–35 seconds. Keep this page open while we verify the details.
      </p>
    </div>
  );
}

function SavedPassportActions({
  onResume,
  onReplace,
  isReplacing,
}: {
  onResume: () => void;
  onReplace: () => void;
  isReplacing: boolean;
}) {
  return (
    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
        <div>
          <h4 className="text-sm font-bold text-emerald-950">Passport pages saved</h4>
          <p className="mt-1 text-sm leading-5 text-emerald-800">
            Continue reviewing the saved images. Replacing them is an explicit action, so back-navigation will not discard a successful upload.
          </p>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <Button type="button" onClick={onResume} disabled={isReplacing}>
          Resume review
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onReplace}
          disabled={isReplacing}
          aria-busy={isReplacing}
        >
          {isReplacing && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
          {isReplacing ? "Replacing saved pages" : "Replace saved pages"}
        </Button>
      </div>
    </div>
  );
}

function PassportPageCaptureControl({
  pageSide,
  file,
  source,
  allowFilesFromDevice,
  onScan,
  onFileChange,
}: {
  pageSide: "front" | "back";
  file: File | null;
  source: "camera" | "file" | null;
  allowFilesFromDevice: boolean;
  onScan: () => void;
  onFileChange: (file: File | null) => void;
}) {
  const label = `Passport ${pageSide} page`;
  const inputId = `passport-${pageSide}-file`;
  const pageNumber = pageSide === "front" ? 1 : 2;

  return (
    <section
      aria-labelledby={`${inputId}-label`}
      className={`rounded-2xl border p-4 transition ${
        file
          ? "border-emerald-200 bg-emerald-50/40 shadow-sm"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
            file ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-600"
          }`}>
            {file ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : pageNumber}
          </span>
          <div className="min-w-0">
            <h5 id={`${inputId}-label`} className="text-sm font-bold text-slate-900">{label}</h5>
            <p id={`${inputId}-hint`} className="mt-1 text-xs leading-5 text-slate-500">
              {pageSide === "front"
                ? "Open the photo and MRZ details page."
                : "Add the opposite passport page for the agency record."}
            </p>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${
          file ? "bg-emerald-100 text-emerald-800" : "bg-amber-50 text-amber-700"
        }`}>
          {file ? "Ready" : "Required"}
        </span>
      </div>

      {file ? (
        <div className="mb-3 flex min-w-0 items-center gap-3 rounded-xl border border-emerald-200 bg-white p-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
            <ImagePlus className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-slate-800" title={file.name}>{file.name}</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              {source === "camera" ? "Live camera scan" : "Selected from device"} · {formatFileSize(file.size)}
            </span>
          </span>
          <button
            type="button"
            onClick={() => onFileChange(null)}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label={`Remove ${label.toLowerCase()}`}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ) : (
        <div className="mb-3 flex min-h-20 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-center">
          <p className="text-xs leading-5 text-slate-500">No {pageSide} page selected yet</p>
        </div>
      )}

      <div className={`grid gap-2 ${allowFilesFromDevice ? "min-[360px]:grid-cols-2" : ""}`}>
        <Button
          type="button"
          variant={file && source === "camera" ? "secondary" : "outline"}
          className="h-11 w-full rounded-xl"
          onClick={onScan}
          aria-label={`${file && source === "camera" ? "Retake" : "Scan"} passport ${pageSide} page with live camera`}
        >
          <Camera className="h-4 w-4" aria-hidden="true" />
          {file && source === "camera" ? "Retake scan" : "Use camera"}
        </Button>

        {allowFilesFromDevice && (
          <>
            <label
              htmlFor={inputId}
              className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 text-sm font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2"
            >
              <ImagePlus className="h-4 w-4" aria-hidden="true" />
              {file && source === "file" ? "Choose another" : "Choose photo"}
            </label>
            <input
              key={`${pageSide}:${source ?? "empty"}:${file?.name ?? ""}`}
              id={inputId}
              type="file"
              accept={PASSPORT_IMAGE_ACCEPT}
              className="sr-only"
              onClick={(event) => {
                event.currentTarget.value = "";
              }}
              onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
              aria-describedby={`${inputId}-hint ${inputId}-formats`}
              aria-label={`Choose passport ${pageSide} page image from device`}
            />
          </>
        )}
      </div>

      {allowFilesFromDevice && (
        <p id={`${inputId}-formats`} className="mt-3 text-xs leading-5 text-slate-400">
          JPG, PNG, WebP, HEIC/HEIF, AVIF, BMP, or TIFF
        </p>
      )}
    </section>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-slate-600">
      <ArrowLeft className="h-4 w-4" />
      Back
    </button>
  );
}

function NameInput({ value, onChange, placeholder = "e.g. John Doe", autoFocus = false }: { value: string; onChange: (value: string) => void; placeholder?: string; autoFocus?: boolean }) {
  return (
    <div className="relative min-w-0">
      <User className="absolute left-4 top-3.5 h-5 w-5 text-slate-400" />
      <Input placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-12 text-base shadow-sm transition-colors placeholder:text-slate-400 focus-visible:ring-blue-600" required autoFocus={autoFocus} />
    </div>
  );
}

function SelectInput({ label, value, values, onChange, disabled = false }: { label: string; value: string; values: string[]; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <label className="block min-w-0 space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-100" required>
        <option value="">Select {label.toLowerCase()}</option>
        {values.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>
  );
}

function ContactInput({
  icon,
  label,
  type,
  value,
  onChange,
  required = false,
  maxLength,
}: {
  icon: ReactNode;
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  maxLength?: number;
}) {
  return (
    <label className="block min-w-0 space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <div className="relative min-w-0">
        <span className="absolute left-3 top-3 text-slate-400">{icon}</span>
        <Input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-10 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white" required={required} maxLength={maxLength} />
      </div>
    </label>
  );
}

function ContactSection({
  email,
  phone,
  departureCity,
  departureCities,
  onEmail,
  onPhone,
  onDepartureCity,
  title,
  emailRequired,
  phoneRequired,
}: {
  email: string;
  phone: string;
  departureCity: string;
  departureCities: string[];
  onEmail: (value: string) => void;
  onPhone: (value: string) => void;
  onDepartureCity: (value: string) => void;
  title: string;
  emailRequired?: boolean;
  phoneRequired?: boolean;
}) {
  return (
    <div className="mt-6 border-t border-slate-100 pt-5">
      <h3 className="mb-3 text-base font-bold text-slate-900">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <ContactInput icon={<Mail className="h-5 w-5" />} label="Email" type="email" value={email} onChange={onEmail} required={emailRequired} />
        <ContactInput icon={<Phone className="h-5 w-5" />} label="WhatsApp active number" type="tel" value={phone} onChange={onPhone} required={phoneRequired} />
        {departureCities.length > 0 && <DepartureCitySelect value={departureCity} cities={departureCities} onChange={onDepartureCity} className="sm:col-span-2" />}
      </div>
    </div>
  );
}

function ConfiguredClientFields({
  baseCityEnabled,
  askNearestDomesticAirport,
  staffCodeEnabled,
  mealPreferenceEnabled,
  baseCity,
  nearestDomesticAirport,
  staffCode,
  mealPreference,
  onBaseCity,
  onNearestDomesticAirport,
  onStaffCode,
  onMealPreference,
}: {
  baseCityEnabled: boolean;
  askNearestDomesticAirport: boolean;
  staffCodeEnabled: boolean;
  mealPreferenceEnabled: boolean;
  baseCity: string;
  nearestDomesticAirport: string;
  staffCode: string;
  mealPreference: string;
  onBaseCity: (value: string) => void;
  onNearestDomesticAirport: (value: string) => void;
  onStaffCode: (value: string) => void;
  onMealPreference: (value: string) => void;
}) {
  if (!baseCityEnabled && !askNearestDomesticAirport && !staffCodeEnabled && !mealPreferenceEnabled) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-slate-100 bg-slate-50 p-4 sm:grid-cols-2">
      {baseCityEnabled && (
        <ContactInput
          icon={<MapPin className="h-5 w-5" />}
          label="Base City"
          type="text"
          value={baseCity}
          onChange={onBaseCity}
          required
        />
      )}
      {askNearestDomesticAirport && (
        <ContactInput
          icon={<MapPin className="h-5 w-5" />}
          label="Nearest Domestic Airport"
          type="text"
          value={nearestDomesticAirport}
          onChange={onNearestDomesticAirport}
          required
          maxLength={120}
        />
      )}
      {staffCodeEnabled && (
        <ContactInput
          icon={<BadgeCheck className="h-5 w-5" />}
          label="Staff Code"
          type="text"
          value={staffCode}
          onChange={onStaffCode}
          required
        />
      )}
      {mealPreferenceEnabled && (
        <label className="block min-w-0 space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Meal Preference</span>
          <div className="relative min-w-0">
            <Utensils className="absolute left-3 top-3.5 h-5 w-5 text-slate-400" />
            <select
              value={mealPreference}
              onChange={(event) => onMealPreference(event.target.value)}
              className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              required
            >
              <option value="">Select meal preference</option>
              <option value="Veg">Veg</option>
              <option value="Non Veg">Non Veg</option>
              <option value="Jain">Jain</option>
            </select>
          </div>
        </label>
      )}
    </div>
  );
}

function DepartureCitySelect({ value, cities, onChange, className = "" }: { value: string; cities: string[]; onChange: (value: string) => void; className?: string }) {
  return (
    <label className={`block min-w-0 space-y-1.5 ${className}`}>
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Nearest International Airport</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100" required>
        <option value="">Select your nearest international airport</option>
        {cities.map((city) => <option key={city} value={city}>{city}</option>)}
      </select>
    </label>
  );
}

function ReviewLayout({
  title,
  description,
  image,
  photoImage,
  backImage,
  fields,
  onBack,
  children,
}: {
  title: string;
  description: string;
  image: ReactNode | null;
  photoImage?: ReactNode | null;
  backImage?: ReactNode | null;
  fields: ExtractedPassportFields | null;
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6 font-sans sm:py-10">
      <div className="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="space-y-4">
          <div>
            <Button type="button" variant="ghost" size="sm" onClick={onBack} className="mb-4 -ml-2 gap-2 text-slate-600 hover:text-slate-900">
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
          </div>
          {image ? (
            <div className="space-y-4">
              {photoImage && (
                <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                  {photoImage}
                </div>
              )}
              <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="relative w-full">
                  {image}
                  <PassportRoiOverlays fields={fields} />
                </div>
              </div>
              {backImage && (
                <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                  {backImage}
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-80 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-400">Passport preview unavailable</div>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

function ReviewWarning() {
  return (
    <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
      <p>Please compare these details with the passport image. Submit only after confirming the information is correct.</p>
    </div>
  );
}

function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="mb-5 rounded-xl border border-red-100 bg-red-50 p-4 text-sm font-medium text-red-700"
    >
      {message}
    </div>
  );
}

function ReviewFields({ fields, onChange }: { fields: Record<string, string>; onChange: (key: string, value: string) => void }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {REVIEW_FIELDS.map((key) => {
        const isDate = key === "date_of_birth" || key === "date_of_issue" || key === "date_of_expiry";
        const isOptional = key === "date_of_issue";
        return (
          <div key={key} className="space-y-1.5">
            <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {toLabel(key)}
            </span>
            {isDate ? (
              <PassportDateInput
                value={fields[key] ?? ""}
                onValueChange={(value) => onChange(key, value)}
                minIso="1900-01-01"
                maxIso={key === "date_of_birth" ? yesterdayIsoDate() : key === "date_of_issue" ? todayIsoDate() : "2200-12-31"}
                required={!isOptional}
                aria-label={toLabel(key)}
                className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-slate-50 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
              />
            ) : (
              <Input
                type="text"
                value={formatReviewFieldValue(key, fields[key] ?? "")}
                onChange={(event) => onChange(key, event.target.value)}
                placeholder="Not extracted"
                required
                aria-label={toLabel(key)}
                className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-slate-50 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function CenteredLoader() {
  return (
    <CenteredShell>
      <div role="status" aria-live="polite">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" aria-hidden="true" />
        <span className="sr-only">Loading secure upload</span>
      </div>
    </CenteredShell>
  );
}

function CenteredShell({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">{children}</div>;
}

function ProcessingScreen({ title, description, progress }: { title: string; description: string; progress?: number | null }) {
  const progressPercent = typeof progress === "number"
    ? Math.max(0, Math.min(100, Math.round(progress * 100)))
    : null;
  return (
    <CenteredShell>
      <div
        aria-busy="true"
        className="flex w-full max-w-md flex-col items-center justify-center text-center"
      >
        <div className="relative mb-8">
          <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl"></div>
          <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
            <Loader2 className="h-10 w-10 animate-spin text-white" aria-hidden="true" />
          </div>
        </div>
        <div role="status" aria-live="polite" aria-atomic="true">
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">{title}</h2>
          <p className="mx-auto max-w-xs text-slate-500">{description}</p>
        </div>
        {progressPercent !== null && (
          <div
            role="progressbar"
            aria-label="Passport processing progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progressPercent}
            className="mt-6 h-2 w-full max-w-xs overflow-hidden rounded-full bg-slate-200"
          >
            <div className="h-full rounded-full bg-blue-600 transition-all duration-500" style={{ width: `${Math.max(8, progressPercent)}%` }} />
          </div>
        )}
      </div>
    </CenteredShell>
  );
}

function getInitialReviewFields(fields: ExtractedPassportFields | null) {
  return REVIEW_FIELDS.reduce<Record<string, string>>((current, key) => {
    const value = fields?.[key];
    current[key] = typeof value === "string" ? value : "";
    return current;
  }, {});
}

function mergeMissingReviewFields(current: Record<string, string>, fields: ExtractedPassportFields | null) {
  return REVIEW_FIELDS.reduce<Record<string, string>>((next, key) => {
    const value = fields?.[key];
    if (typeof value === "string" && value.trim() && !next[key]?.trim()) {
      next[key] = value;
    }
    return next;
  }, { ...current });
}

function hasMissingRequiredFields(fields: Record<string, string>) {
  return REQUIRED_REVIEW_FIELDS.some((key) => !fields[key]?.trim());
}

function formatReviewFieldValue(key: typeof REVIEW_FIELDS[number], value: string) {
  if (!isRecognizedPassportCountryCode(value)) return value;
  if (key === "nationality") return formatPassportNationality(value);
  if (key === "issuing_country") return formatPassportCountry(value);
  return value;
}

function ExtractionNotice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="status" aria-live="polite" className="mb-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-medium leading-5 text-blue-900">
      {message}
    </div>
  );
}

function DocumentVerificationBlock({
  gate,
  onRetry,
  onReplace,
  isRetrying,
  isReplacing,
}: {
  gate: Extract<PassportDocumentVerificationGate, { accepted: false }>;
  onRetry: () => void;
  onReplace: () => void;
  isRetrying: boolean;
  isReplacing: boolean;
}) {
  const busy = isRetrying || isReplacing;
  return (
    <div
      role="alert"
      className="rounded-2xl border border-amber-300 bg-amber-50 p-5 text-amber-950"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <h3 className="font-bold">Passport page not verified</h3>
          <p className="mt-2 text-sm leading-6">{gate.message}</p>
          <p className="mt-2 text-xs leading-5 text-amber-800">
            Passport fields stay locked and cannot be submitted until this check passes.
          </p>
        </div>
      </div>
      <Button
        type="button"
        className="mt-4 h-11 w-full"
        onClick={gate.action === "retry" ? onRetry : onReplace}
        disabled={busy}
      >
        {gate.action === "retry"
          ? isRetrying
            ? "Retrying verification"
            : "Retry verification on saved image"
          : isReplacing
            ? "Preparing replacement"
            : "Replace passport pages"}
      </Button>
    </div>
  );
}

function hasValidReviewDates(fields: Record<string, string>) {
  const dateOfBirth = fields.date_of_birth?.trim() ?? "";
  const dateOfIssue = fields.date_of_issue?.trim() ?? "";
  const dateOfExpiry = fields.date_of_expiry?.trim() ?? "";
  if (![dateOfBirth, dateOfExpiry].every(isValidIsoDate)) return false;
  if (dateOfIssue && !isValidIsoDate(dateOfIssue)) return false;

  const today = todayIsoDate();
  if (dateOfBirth >= today || (dateOfIssue && dateOfIssue > today)) return false;
  if (dateOfIssue && dateOfIssue <= dateOfBirth) return false;
  if (dateOfIssue && dateOfExpiry && dateOfIssue >= dateOfExpiry) return false;
  if (dateOfExpiry <= dateOfBirth) return false;
  return true;
}

function cleanReviewFields(fields: Record<string, string>) {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
}

function isValidIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return year >= 1900
    && year <= 2200
    && parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}

function todayIsoDate() {
  const now = new Date();
  const localDate = new Date(now.getTime() - (now.getTimezoneOffset() * 60_000));
  return localDate.toISOString().slice(0, 10);
}

function toLabel(value: string) {
  if (value === "given_names") return "Name";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function createIdempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (
    typeof crypto !== "undefined"
    && typeof crypto.getRandomValues === "function"
  ) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    return Array.from(
      bytes,
      (value) => value.toString(16).padStart(2, "0"),
    ).join("");
  }
  throw new Error(
    "Secure random number generation is required for passport upload.",
  );
}

function yesterdayIsoDate() {
  const today = todayIsoDate();
  return previousPassportIsoDate(today) ?? today;
}

function isExtractionTerminal(submission: PassportSubmission) {
  return [
    "extraction_complete",
    "extraction_partial",
    "extraction_failed",
    "ready_for_review",
  ].includes(submission.extraction_status)
    || submission.status === "ready_for_client_review"
    || submission.status === "review_required"
    || submission.status === "failed";
}

function extractionNoticeFor(submission: PassportSubmission) {
  if (submission.extraction_status === "extraction_failed" || submission.status === "failed") {
    return "Your passport pages were saved, but some details could not be read automatically. Enter the missing fields manually or retry reading the stored image.";
  }
  if (submission.extraction_status === "extraction_partial") {
    return "Your passport pages were saved. Some details could not be read confidently, so check and complete the missing fields manually.";
  }
  return null;
}

function canRetryExtractionFor(submission: PassportSubmission) {
  return submission.extraction_status === "extraction_failed" || submission.status === "failed";
}

function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "Size unavailable";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function sleep(delayMs: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Operation cancelled", "AbortError"));
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Operation cancelled", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function stageLabel(stage: string) {
  const labels: Record<string, string> = {
    queued: "Your passport verification is queued and will begin shortly.",
    retry_queued: "Your verification is queued safely while we handle higher traffic.",
    starting: "Starting secure passport processing.",
    downloading_image: "Preparing the passport image for extraction.",
    extracting_passport_fields: "Extracting passport details from the passport image.",
    verifying_passport_fields: "Verifying the extracted passport details against the image.",
    saving_extraction_result: "Preparing the verified details for your review.",
    completed: "Passport details are ready for review.",
  };
  return labels[stage] ?? stage.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function PassportRoiOverlays({ fields }: { fields: ExtractedPassportFields | null }) {
  const boxes = roiOverlayBoxes(fields);
  if (boxes.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {boxes.map((box) => (
        <div key={box.field} className="absolute rounded-sm border-2 border-red-500 shadow-[0_0_0_9999px_rgba(239,68,68,0.04)]" style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${(box.right - box.left) * 100}%`, height: `${(box.bottom - box.top) * 100}%` }}>
          <span className="absolute -top-6 left-0 rounded bg-red-600 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white shadow-sm">{toLabel(box.field)}</span>
        </div>
      ))}
    </div>
  );
}

function roiOverlayBoxes(fields: ExtractedPassportFields | null) {
  const provenance = fields?.field_provenance;
  if (!provenance) return [];

  return Object.entries(provenance)
    .map(([field, item]) => {
      const bbox = item?.debug?.image_relative_bbox;
      if (!isNormalizedBbox(bbox)) return null;
      return { field, left: bbox[0], top: bbox[1], right: bbox[2], bottom: bbox[3] };
    })
    .filter((box): box is { field: string; left: number; top: number; right: number; bottom: number } => Boolean(box));
}

function isNormalizedBbox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value)
    && value.length === 4
    && value.every((item) => typeof item === "number" && item >= 0 && item <= 1)
    && value[2] > value[0]
    && value[3] > value[1];
}

function submitErrorMessage(error: unknown) {
  if (isPublicApiError(error)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? "Could not submit reviewed details. Please check the contact details.";
  }
  return "Could not submit reviewed details. Please try again.";
}

function errorMessage(error: unknown, fallback: string) {
  if (isPublicApiError(error)) return error.message;
  if (error instanceof Error && !(error instanceof AxiosError)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? fallback;
  }
  return fallback;
}

function uploadPersistenceErrorMessage(error: unknown) {
  if (isPublicApiError(error)) return error.message;
  if (isAxiosError(error)) {
    const detail = extractApiErrorDetail(error.response?.data);
    if (error.response?.status && error.response.status >= 400 && error.response.status < 500) {
      return detail ?? "The passport pages were rejected. Check the file type and size, then try again.";
    }
    return detail
      ?? "We could not confirm that the passport pages were saved. Retry safely; the same upload will not create a duplicate.";
  }
  return "We could not confirm that the passport pages were saved. Check your connection and retry safely.";
}

function isPublicApiError(error: unknown): error is { code: string; message: string } {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { code?: unknown; message?: unknown };
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

function extractApiErrorDetail(payload: unknown) {
  if (!payload || typeof payload !== "object") return null;
  const data = payload as { detail?: unknown; error?: { message?: unknown } };
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const record = item as { msg?: unknown; loc?: unknown };
        const label = Array.isArray(record.loc) ? record.loc.slice(1).join(".") : "";
        return typeof record.msg === "string" ? [label, record.msg].filter(Boolean).join(": ") : null;
      })
      .filter(Boolean)
      .join(" ");
  }
  if (typeof data.error?.message === "string") return data.error.message;
  return null;
}
