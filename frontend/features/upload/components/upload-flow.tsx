"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { isUploadFieldRequired, type RequiredUploadField } from "@/features/passports/types/upload-configuration";
import type { PassportSubmission } from "@/types/passport.types";
import {
  CheckCircle2,
  User,
  Users
} from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useInstructionLanguage } from "../hooks/use-instruction-language";
import { usePublicFlowTelemetry } from "../hooks/use-public-flow-telemetry";
import { useUploadContactVerification } from "../hooks/use-upload-contact-verification";
import { useUploadDocuments } from "../hooks/use-upload-documents";
import { useUploadFamily } from "../hooks/use-upload-family";
import { useUploadOperation } from "../hooks/use-upload-operation";
import { useUploadSubmission } from "../hooks/use-upload-submission";
import { getUploadFlowSettings, passportBundleError } from "../services/configured-upload";
import { acceptPassportPage } from "../services/passport-capture-transition";
import {
  passportDocumentVerificationGate,
} from "../services/passport-document-verification";
import {
  buildQualifierSelectionRequest,
  qualifierChoiceKey,
  type QualifierPath,
} from "../services/relation-qualifier";
import { runUploadFlowBootstrap } from "../services/upload-flow-bootstrap";
import {
  emptyDocumentBundle,
  errorMessage,
  isClientSubmissionComplete
} from "../services/upload-flow-helpers";
import {
  clearQualifierSelectionToken,
  createIdempotencyKey,
  readUploadRecoveryRecord,
  writeQualifierSelectionToken
} from "../services/upload-flow-session";
import { PassportUploadPage } from "./passport-upload-page";
import { UploadLinkErrorScreen } from "./upload-link-error-screen";
import { UploadFamilyReview, UploadSingleReview } from "./upload-review-panels";

import { RelationQualifierStep } from "./relation-qualifier-step";
import { UploadDocumentOptions } from "./upload-flow-document-options";
import {
  NameInput,
  SelectInput
} from "./upload-flow-fields";
import {
  SavedPassportActions,
  VisaSelfieChoice,
} from "./upload-flow-passport-picker";
import {
  BackButton,
  CenteredLoader,
  ChoiceCard,
  ErrorMessage,
  ProcessingScreen,
  UploadHeader,
} from "./upload-flow-shell";
import {
  resolveUploadLinkFailure,
  UploadRecoveryScreen,
  UploadSuccessScreen,
} from "./upload-flow-status";
import {
  FAMILY_RELATIONS,
  GENDERS,
  MAX_FAMILY_MEMBERS,
  MIN_FAMILY_MEMBERS,
  PASSIVE_PROGRESS_STEPS,
} from "./upload-flow.constants";
import type {
  AgentEmployeeType,
  FlowMode,
  PassportDocumentBundle,
  UploadFlowStep as Step
} from "./upload-flow.types";

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
  const { data: group, isLoading, error, refetch: refetchLink, isFetching: isFetchingLink } = useUploadLinkByToken(token);
  const [linkError, setLinkError] = useState<unknown>(null);

  const [step, setStep] = useState<Step>("BOOTSTRAP");
  const [flowMode, setFlowMode] = useState<FlowMode | null>(null);
  const [qualifierPath, setQualifierPath] = useState<QualifierPath>(null);
  const [qualifierRelationCode, setQualifierRelationCode] = useState("");
  const [qualifierOtherRelation, setQualifierOtherRelation] = useState("");
  const [qualifierSelectionToken, setQualifierSelectionToken] = useState<string | null>(null);
  const [persistedQualifierChoice, setPersistedQualifierChoice] = useState<string | null>(null);
  const [isSavingQualifier, setIsSavingQualifier] = useState(false);
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
  const { familyMembers, activeFamilyIndex, familyCountInput, setActiveFamilyIndex,
    updateFamilyMember, handleFamilyCountInput, normalizeFamilyCountInput } = useUploadFamily();

  const [uploadError, setUploadError] = useState<string | null>(null);
  const [visaSelfie, setVisaSelfie] = useState<File | null>(null);
  const [visaPhotoSource, setVisaPhotoSource] = useState<"camera" | "file" | null>(null);
  const [passportMethod, setPassportMethod] = useState<"camera" | "file">("camera");
  const [documentBundle, setDocumentBundle] = useState<PassportDocumentBundle>(() => emptyDocumentBundle());
  const [scannerPageSide, setScannerPageSide] = useState<"front" | "back">("front");
  const qualifierSaveInFlightRef = useRef(false);
  const initializedGroupTokenRef = useRef<string | null>(null);
  const flowSettings = getUploadFlowSettings(group);
  const {
    uploadConfig, groupId,
    baseCityEnabled, staffCodeEnabled, agentEmployeeCodeEnabled, designationEnabled,
    agencyDealershipNameEnabled, mealPreferenceEnabled, selfieEnabled, selfieRequired,
    passportEnabled, passportRequired, allowFilesFromDevice, askNearestDomesticAirport,
    relationWithQualifierEnabled,
  } = flowSettings;
  const instructions = useInstructionLanguage(token, uploadConfig);
  const requiredField = (field: RequiredUploadField) => isUploadFieldRequired(uploadConfig, field);
  const activeFamilyMember = familyMembers[activeFamilyIndex] ?? null;
  const activeVisaSelfie = flowMode === "family" ? activeFamilyMember?.visaSelfie ?? null : visaSelfie;
  const activeVisaPhotoSource = flowMode === "family" ? activeFamilyMember?.visaPhotoSource ?? null : visaPhotoSource;
  const requiresPassportReview = (saved: PassportSubmission) => Boolean(saved.image_s3_key);
  const canReviewSubmission = (saved: PassportSubmission) => requiresPassportReview(saved)
    ? isClientSubmissionComplete(saved) || saved.manual_review_submission_allowed === true || passportDocumentVerificationGate(saved).accepted
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


  const saveQualifierChoice = async () => {
    if (qualifierSaveInFlightRef.current) return;
    const selectionRequest = buildQualifierSelectionRequest(
      qualifierPath,
      qualifierRelationCode,
      group?.qualifier_relation_options ?? [],
      qualifierOtherRelation,
      { listEnabled: uploadConfig.qualifier_relation_list_enabled, otherEnabled: uploadConfig.qualifier_relation_other_enabled },
    );
    if (!selectionRequest || qualifierPath === null) return;
    const choiceKey = qualifierChoiceKey(qualifierPath, qualifierRelationCode, qualifierOtherRelation);
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
    setUploadError(null);
  };

  const chooseMode = (mode: FlowMode) => {
    setFlowMode(mode);
    setUploadError(null);
    setStep(mode === "single" ? "METHOD_SELECT" : "FAMILY_SETUP");
  };

  const operation = useUploadOperation(token);
  const documentController = useUploadDocuments({ token, step, flowMode, activeFamilyIndex, familyMembers, updateFamilyMember, clientName, setClientName, submission, setSubmission, setReviewFields, singleUploadIdempotencyKey, setSingleUploadIdempotencyKey, qualifierSelectionToken, activeVisaPhotoSource, setVisaSelfie, setDocumentBundle, selectFamilyMember, setStep, setUploadError, setExtractionNotice, setCanRetryExtraction, operation });
  const { processUpload, handleBackToUploadMethods, replaceSavedPassport,
    processingProgress, setProcessingProgress, processingStage, setProcessingStage, extractingSubmissionId,
    isPreparingFile, isReplacingSavedPassport, resumeSubmissionId, queueSubmissionResume,
  } = documentController;

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
        setLinkError,
        setSingleUploadIdempotencyKey,
        setSubmission,
        setClientName,
        setStep,
        setReviewFields,
        setExtractionNotice,
        setCanRetryExtraction,
        setProcessingProgress,
        setProcessingStage,
        queueSubmissionResume,
        setFlowMode,
        setUploadError,
        setQualifierSelectionToken,
        setPersistedQualifierChoice,
        setQualifierPath,
        setQualifierRelationCode,
        setQualifierOtherRelation,
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
    token, queueSubmissionResume, setProcessingProgress, setProcessingStage,
  ]);

  const contactVerification = useUploadContactVerification({
    token, step, submission, sessionId: singleUploadIdempotencyKey, name: clientName,
    email: clientEmail, phone: clientPhone, familyMembers,
    onSingleContact: (email, phone) => { setClientEmail(email); setClientPhone(phone); },
    onFamilyContact: (index, email, phone) => updateFamilyMember(index, { email, phone }),
    onBack: () => handleBackToUploadMethods(),
  });

  const startFamilyUploads = (event: React.FormEvent) => {
    event.preventDefault();
    const invalidMember = familyMembers.find((member) => member.name.trim().length < 2 || !member.relation || !member.gender);
    if (invalidMember) {
      setUploadError("Enter name, relation, and gender for every family member.");
      return;
    }
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

  const acceptPassportCapture = (
    file: File,
    pageSide: "front" | "back",
    source: "camera" | "file",
  ) => {
    const transition = acceptPassportPage(documentBundle, file, pageSide, source);
    setDocumentBundle(transition.bundle);
    setUploadError(null);
    setScannerPageSide(transition.scannerPageSide);
    setStep(transition.nextStep);
  };

  const handleCameraCapture = (file: File) => {
    acceptPassportCapture(file, scannerPageSide, "camera");
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
      updateFamilyMember(activeFamilyIndex, { visaSelfie: file, visaPhotoSource: source });
    } else {
      setVisaSelfie(file);
      setVisaPhotoSource(source);
    }
    setStep("METHOD_SELECT");
  };

  const handleReviewFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleFamilyReviewFieldChange = (index: number, key: string, value: string) => {
    updateFamilyMember(index, (member) => ({ reviewFields: { ...member.reviewFields, [key]: value } }));
  };

  const { handleFinalSubmit, handleFamilySubmit } = useUploadSubmission({
    token, submission, singleUploadIdempotencyKey, familyMembers, familyGroupId, updateFamilyMember,
    contactVerification, operation, setSubmission, setClientName, setStep, setUploadError, setLinkError,
    canReviewSubmission, requiresPassportReview, settings: flowSettings,
    draft: { clientName, clientEmail, clientPhone, reviewFields, departureCity, baseCity, nearestDomesticAirport, staffCode, agentEmployeeCode, designation, agencyDealershipName, mealPreference, customAnswers, customDetailAnswers },
  });

  const retrySavedUploadRecovery = () => {
    initializedGroupTokenRef.current = null;
    setUploadError(null);
    setStep("BOOTSTRAP");
    reportPublicFlowOnce("recovery_started");
    setRecoveryRetryNonce((current) => current + 1);
  };

  const documentChoices = <UploadDocumentOptions config={uploadConfig} allowFilesFromDevice={allowFilesFromDevice} flowMode={flowMode} clientName={clientName} onClientName={setClientName} passportMethod={passportMethod} bundle={documentBundle} onBundleChange={setDocumentBundle} onScan={openPassportScanner} onFileSelect={(pageSide, file) => acceptPassportCapture(file, pageSide, "file")} onUpload={handleBundleUpload} onSkip={continueWithoutPassport} onOpenUpload={() => {
    if (passportMethod !== "file") setDocumentBundle(emptyDocumentBundle());
    setPassportMethod("file");
    setUploadError(null);
    setStep("PASSPORT_UPLOAD");
  }} />;

  const linkFailure = resolveUploadLinkFailure({ error, linkError, isLoading, hasGroup: Boolean(group) });
  if (linkFailure) {
    return <UploadLinkErrorScreen error={linkFailure.error} isRetrying={isFetchingLink} onRetry={() => {
      void refetchLink().then((result) => {
        if (result.error) { setLinkError(result.error); return; }
        setLinkError(null);
        initializedGroupTokenRef.current = null;
        setRecoveryRetryNonce((value) => value + 1);
      });
    }} />;
  }

  if (isLoading || step === "BOOTSTRAP" || !group) return <CenteredLoader />;

  if (step === "RECOVERY_ERROR") {
    return <UploadRecoveryScreen error={uploadError} onRetry={retrySavedUploadRecovery} />;
  }

  if (isPreparingFile) {
    return <ProcessingScreen title="Preparing Passport Image" description="Straightening the capture and optimizing it before secure upload." showPassportMotion={Boolean(documentBundle.front)} />;
  }

  if (step === "PASSPORT_UPLOAD" && passportEnabled && allowFilesFromDevice) {
    return <PassportUploadPage bundle={documentBundle} config={uploadConfig} instructions={instructions} onChange={setDocumentBundle} onContinue={handleBundleUpload} onBack={() => setStep("METHOD_SELECT")} error={uploadError} />;
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
        instructions={instructions}
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

  if (step === "UPLOADING") {
    return (
      <ProcessingScreen
        title={extractingSubmissionId ? "Reading Passport Details" : "Saving Travel Documents"}
        description={processingStage}
        progress={processingProgress}
        showPassportMotion={Boolean(documentBundle.front || resumeSubmissionId || extractingSubmissionId)}
      />
    );
  }

  if (step === "SUBMITTING") {
    return <ProcessingScreen title="Submitting Reviewed Details" description="Sending your reviewed information to your travel agency." />;
  }

  if (contactVerification.page) return contactVerification.page;

  if (step === "REVIEW" && submission) {
    return <UploadSingleReview token={token} settings={flowSettings} documents={documentController} contactVerification={contactVerification} canReviewSubmission={canReviewSubmission} uploadError={uploadError} departureCity={departureCity} setDepartureCity={setDepartureCity} onSubmit={handleFinalSubmit}
      submission={submission} singleUploadIdempotencyKey={singleUploadIdempotencyKey}
      review={{ clientName, clientEmail, clientPhone, reviewFields, departureCity, baseCity, nearestDomesticAirport, staffCode, agentEmployeeCode, designation, agencyDealershipName, mealPreference, customAnswers, customDetailAnswers }}
      configuredFields={{ config: uploadConfig, baseCityEnabled: baseCityEnabled, askNearestDomesticAirport: askNearestDomesticAirport, staffCodeEnabled: staffCodeEnabled, agentEmployeeCodeEnabled: agentEmployeeCodeEnabled, designationEnabled: designationEnabled, agencyDealershipNameEnabled: agencyDealershipNameEnabled, mealPreferenceEnabled: mealPreferenceEnabled, baseCity: baseCity, nearestDomesticAirport: nearestDomesticAirport, staffCode: staffCode, agentEmployeeType: agentEmployeeType, agentEmployeeCode: agentEmployeeCode, designation: designation, agencyDealershipName: agencyDealershipName, mealPreference: mealPreference, onBaseCity: setBaseCity, onNearestDomesticAirport: setNearestDomesticAirport, onStaffCode: setStaffCode, onAgentEmployeeType: setAgentEmployeeType, onAgentEmployeeCode: setAgentEmployeeCode, onDesignation: setDesignation, onAgencyDealershipName: setAgencyDealershipName, onMealPreference: setMealPreference }}
      requiresPassportReview={requiresPassportReview} extractionNotice={extractionNotice} canRetryExtraction={canRetryExtraction}
      setClientName={setClientName} handleReviewFieldChange={handleReviewFieldChange}
      setCustomAnswers={setCustomAnswers} setCustomDetailAnswers={setCustomDetailAnswers} />;
  }
  if (step === "FAMILY_REVIEW") {
    return <UploadFamilyReview token={token} settings={flowSettings} documents={documentController} contactVerification={contactVerification} canReviewSubmission={canReviewSubmission} uploadError={uploadError} departureCity={departureCity} setDepartureCity={setDepartureCity} onSubmit={handleFamilySubmit}
      familyMembers={familyMembers} hasBlockedFamilyVerification={hasBlockedFamilyVerification}
      setStep={setStep} selectFamilyMember={selectFamilyMember} updateFamilyMember={updateFamilyMember}
      handleFamilyReviewFieldChange={handleFamilyReviewFieldChange} />;
  }

  if (step === "SUCCESS") {
    return (
      <UploadSuccessScreen
        flowMode={flowMode}
        familyMembers={familyMembers}
        submission={submission}
        clientName={clientName}
        groupName={group.name}
      />
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
                otherRelation={qualifierOtherRelation}
                listEnabled={uploadConfig.qualifier_relation_list_enabled}
                otherEnabled={uploadConfig.qualifier_relation_other_enabled}
                options={group.qualifier_relation_options ?? []}
                isSaving={isSavingQualifier}
                onPathChange={(nextPath) => {
                  setQualifierPath(nextPath);
                  if (nextPath === "self") {
                    setQualifierRelationCode("");
                    setQualifierOtherRelation("");
                  }
                  setUploadError(null);
                }}
                onRelationChange={setQualifierRelationCode}
                onOtherRelationChange={setQualifierOtherRelation}
                onContinue={saveQualifierChoice}
              />
              {!requiredField("relation_with_qualifier") && <Button type="button" variant="ghost" className="mt-4 h-11 w-full" onClick={() => {
                clearQualifierSelectionToken(token);
                setQualifierSelectionToken(null);
                setPersistedQualifierChoice(null);
                setQualifierPath(null);
                setQualifierRelationCode("");
                setQualifierOtherRelation("");
                setFlowMode("single");
                setStep("METHOD_SELECT");
              }}>Continue without relationship details</Button>}
            </>
          )}

          {step === "FAMILY_SETUP" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <BackButton onClick={() => setStep("MODE_SELECT")} />
              <h3 className="mb-2 text-xl font-bold text-slate-900">Family Details</h3>
              <p className="mb-5 text-sm leading-6 text-slate-500 sm:mb-6">Enter every member first. After saving the documents, every member must provide an email and verify their WhatsApp number before filling further details. You may use the same family number for multiple members.</p>
              <form onSubmit={startFamilyUploads} className="space-y-4 sm:space-y-5">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">How many people?</span>
                  <Input
                    type="number"
                    min={MIN_FAMILY_MEMBERS}
                    max={MAX_FAMILY_MEMBERS}
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
                            className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-3 text-left transition ${isActive ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-200"
                              }`}
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-bold text-slate-950">{member.name}</span>
                              <span className="block truncate text-xs text-slate-500">{member.relation} • {member.gender}</span>
                            </span>
                            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${isUploaded ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"
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
