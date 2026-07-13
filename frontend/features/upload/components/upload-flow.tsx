"use client";

import { useRef, useState } from "react";
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
  Phone,
  Upload,
  User,
  Users,
} from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { useSubmitClientPassportReview, useUploadPassport } from "../hooks/use-upload";
import { uploadApi } from "../api/upload.api";
import { normalizePassportFile } from "../services/passport-perspective-correction";
import { SmartCamera } from "./smart-camera";

interface UploadFlowProps {
  token: string;
}

type FlowMode = "single" | "family";
type Step =
  | "MODE_SELECT"
  | "NAME_INPUT"
  | "FAMILY_SETUP"
  | "METHOD_SELECT"
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
  submission: PassportSubmission | null;
  reviewFields: Record<string, string>;
}

const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "issuing_country",
  "date_of_birth",
  "date_of_expiry",
  "sex",
] as const;

const RELATIONS = ["Head", "Spouse", "Son", "Daughter", "Father", "Mother", "Brother", "Sister", "Other"];
const GENDERS = ["Male", "Female", "Other", "Prefer not to say"];

export function UploadFlow({ token }: UploadFlowProps) {
  const { data: group, isLoading, error } = useUploadLinkByToken(token);
  const { mutateAsync: uploadPassport } = useUploadPassport();
  const { mutateAsync: submitClientReview } = useSubmitClientPassportReview();

  const [step, setStep] = useState<Step>("MODE_SELECT");
  const [flowMode, setFlowMode] = useState<FlowMode | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [departureCity, setDepartureCity] = useState("");
  const [submission, setSubmission] = useState<PassportSubmission | null>(null);
  const [reviewFields, setReviewFields] = useState<Record<string, string>>({});

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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const departureCities = group?.departure_cities ?? [];
  const activeFamilyMember = familyMembers[activeFamilyIndex] ?? null;

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
    setActiveFamilyIndex(familyMembers.findIndex((member) => !member.submission) === -1 ? 0 : familyMembers.findIndex((member) => !member.submission));
    setStep("METHOD_SELECT");
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files?.[0]) return;
    await processUpload(event.target.files[0]);
    event.target.value = "";
  };

  const handleCameraCapture = async (file: File) => {
    await processUpload(file);
  };

  const processUpload = async (file: File) => {
    const uploadName = flowMode === "family" ? activeFamilyMember?.name : clientName;
    if (!uploadName || uploadName.trim().length < 2) {
      setUploadError("Enter the passenger name before uploading.");
      return;
    }
    try {
      setUploadError(null);
      setIsPreparingFile(true);
      const normalized = await normalizePassportFile(file);
      setIsPreparingFile(false);
      setStep("UPLOADING");
      const result = await uploadPassport({ token, client_name: uploadName.trim(), file: normalized.file });
      const completed = isExtractionComplete(result) ? result : await waitForExtraction(result);

      if (flowMode === "family") {
        const fields = getInitialReviewFields(completed.extracted_fields);
        setFamilyMembers((current) => current.map((member, index) => (
          index === activeFamilyIndex ? { ...member, submission: completed, reviewFields: fields } : member
        )));
        const nextIndex = familyMembers.findIndex((member, index) => index !== activeFamilyIndex && !member.submission);
        if (nextIndex >= 0) {
          setActiveFamilyIndex(nextIndex);
          setStep("METHOD_SELECT");
        } else {
          setStep("FAMILY_REVIEW");
        }
        return;
      }

      setSubmission(completed);
      setReviewFields(getInitialReviewFields(completed.extracted_fields));
      setStep("REVIEW");
    } catch (error: unknown) {
      setIsPreparingFile(false);
      setProcessingProgress(null);
      setProcessingStage("Uploading securely");
      setUploadError(errorMessage(error, "Failed to upload file. Please try again."));
      setStep("METHOD_SELECT");
    }
  };

  const waitForExtraction = async (initial: PassportSubmission) => {
    let current = initial;
    setSubmission(current);
    setProcessingProgress(current.processing_progress ?? 0.05);
    setProcessingStage(stageLabel(current.processing_stage ?? current.processing_job_status ?? "queued"));

    const deadline = Date.now() + 120_000;
    let delayMs = 700;
    while (Date.now() < deadline) {
      await sleep(delayMs);
      current = await uploadApi.getUploadStatus(token, current.id);
      setSubmission(current);
      setProcessingProgress(current.processing_progress ?? null);
      setProcessingStage(stageLabel(current.processing_stage ?? current.processing_job_status ?? "processing"));

      if (isExtractionComplete(current)) {
        setProcessingProgress(1);
        return current;
      }
      if (current.status === "failed") {
        throw new Error(current.error_message ?? "Automatic extraction failed. Please scan again.");
      }
      delayMs = Math.min(1600, delayMs + 150);
    }
    throw new Error("Processing is taking longer than expected. Please try again in a moment.");
  };

  const handleReviewFieldChange = (key: string, value: string) => {
    setReviewFields((current) => ({ ...current, [key]: value }));
  };

  const handleFamilyReviewFieldChange = (index: number, key: string, value: string) => {
    setFamilyMembers((current) => current.map((member, itemIndex) => (
      itemIndex === index ? { ...member, reviewFields: { ...member.reviewFields, [key]: value } } : member
    )));
  };

  const handleScanAgain = async () => {
    if (!submission) return;
    try {
      setUploadError(null);
      setIsScanningAgain(true);
      const refreshed = await uploadApi.scanAgain(token, submission.id);
      setSubmission(refreshed);
      setReviewFields((current) => mergeMissingReviewFields(current, refreshed.extracted_fields));
    } catch (error: unknown) {
      setUploadError(errorMessage(error, "Could not scan the stored passport again. Please try again."));
    } finally {
      setIsScanningAgain(false);
    }
  };

  const handleBackToUploadMethods = async () => {
    const draft = submission;
    setSubmission(null);
    setReviewFields({});
    setUploadError(null);
    setProcessingProgress(null);
    setProcessingStage("Uploading securely");
    setStep("METHOD_SELECT");
    if (draft) {
      try {
        await uploadApi.discardUpload(token, draft.id);
      } catch {
        // Draft cleanup failure should not block a fresh upload attempt.
      }
    }
  };

  const handleFinalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!submission) return;
    if (!validateReviewFields(reviewFields)) {
      setUploadError("Please fill all passport fields before submitting. You can type corrections manually or scan again.");
      return;
    }
    if (departureCities.length > 0 && !departureCity) {
      setUploadError("Please select your departure city before submitting.");
      return;
    }

    try {
      setUploadError(null);
      setStep("SUBMITTING");
      await submitClientReview({
        submissionId: submission.id,
        group_token: token,
        confirmed_fields: cleanReviewFields(reviewFields),
        client_email: clientEmail,
        client_phone: clientPhone,
        departure_city: departureCity || null,
        submission_mode: "single",
      });
      setStep("SUCCESS");
    } catch (error: unknown) {
      setUploadError(submitErrorMessage(error));
      setStep("REVIEW");
    }
  };

  const handleFamilySubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (departureCities.length > 0 && !departureCity) {
      setUploadError("Please select the family departure city before submitting.");
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
    const invalidReview = familyMembers.find((member) => hasMissingRequiredFields(member.reviewFields));
    if (invalidReview) {
      setUploadError(`Fill all passport fields for ${invalidReview.name}.`);
      return;
    }

    try {
      setUploadError(null);
      setStep("SUBMITTING");
      for (const [index, member] of familyMembers.entries()) {
        if (!member.submission) continue;
        await submitClientReview({
          submissionId: member.submission.id,
          group_token: token,
          confirmed_fields: cleanReviewFields(member.reviewFields),
          client_email: member.email.trim() || null,
          client_phone: member.phone.trim() || null,
          departure_city: departureCity || null,
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
    }
  };

  if (isLoading) return <CenteredLoader />;

  if (error || !group) {
    return (
      <CenteredShell>
        <div className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-8 text-center shadow-lg">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
            <AlertCircle className="h-7 w-7 text-red-600" />
          </div>
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Link Unavailable</h2>
          <p className="text-base text-slate-500">This secure group link is invalid, closed, or expired.</p>
        </div>
      </CenteredShell>
    );
  }

  if (step === "CAMERA") {
    return <SmartCamera onCapture={handleCameraCapture} onCancel={() => setStep("METHOD_SELECT")} />;
  }

  if (isPreparingFile) {
    return <ProcessingScreen title="Preparing Passport Image" description="Straightening the capture and optimizing it before secure upload." />;
  }

  if (step === "UPLOADING") {
    return (
      <ProcessingScreen
        title="Processing Passport"
        description={`${processingStage}. Reading the passport details so you can verify them before final submission.`}
        progress={processingProgress}
      />
    );
  }

  if (step === "SUBMITTING") {
    return <ProcessingScreen title="Submitting Reviewed Details" description="Sending the verified passport information to your travel agency." />;
  }

  if (step === "REVIEW" && submission) {
    return (
      <ReviewLayout
        title="Verify Passport Details"
        description="Please check every field carefully before submitting."
        image={submission.image_url ? API_ENDPOINTS.passports.uploadImage(token, submission.id) : null}
        fields={submission.extracted_fields}
        onBack={handleBackToUploadMethods}
      >
        <form onSubmit={handleFinalSubmit} className="rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-6">
          <ReviewWarning />
          <ErrorMessage message={uploadError} />
          {hasMissingRequiredFields(reviewFields) && (
            <div className="mb-5 rounded-xl border border-blue-100 bg-blue-50 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm font-medium text-blue-800">Some fields were not read clearly. Correct them manually or scan again.</p>
                <Button type="button" variant="secondary" size="sm" onClick={handleScanAgain} disabled={isScanningAgain}>
                  {isScanningAgain ? "Scanning" : "Scan Again"}
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
          <Button type="submit" size="lg" className="mt-6 h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700">
            Submit Verified Details
          </Button>
        </form>
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
          {familyMembers.map((member, index) => (
            <section key={member.localId} className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
              <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <h2 className="text-lg font-bold text-slate-900">{member.name}</h2>
                  <p className="text-sm text-slate-500">{member.relation} • {member.gender}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setActiveFamilyIndex(index);
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
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={API_ENDPOINTS.passports.uploadImage(token, member.submission.id)}
                        alt={`${member.name} passport`}
                        className="block h-auto w-full"
                      />
                      <PassportRoiOverlays fields={member.submission.extracted_fields} />
                    </div>
                  ) : (
                    <div className="flex min-h-72 items-center justify-center text-sm text-slate-400">Passport preview unavailable</div>
                  )}
                </div>
                <div>
                  <ReviewWarning />
                  <ReviewFields fields={member.reviewFields} onChange={(key, value) => handleFamilyReviewFieldChange(index, key, value)} />
                </div>
              </div>
              <div className="mt-5 rounded-2xl border border-slate-100 bg-slate-50 p-3 sm:p-4">
                <h3 className="text-sm font-bold text-slate-900">Individual broadcast contact optional</h3>
                <p className="mt-1 text-xs leading-5 text-slate-500">If provided, this member can receive only their own details later. The head still receives all details.</p>
                <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
                  <ContactInput icon={<Mail className="h-5 w-5" />} label="Member email" type="email" value={member.email} onChange={(value) => updateFamilyMember(index, { email: value })} />
                  <ContactInput icon={<Phone className="h-5 w-5" />} label="Member WhatsApp active number" type="tel" value={member.phone} onChange={(value) => updateFamilyMember(index, { phone: value })} />
                </div>
              </div>
            </section>
          ))}
          <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-xl shadow-slate-200/50 sm:rounded-3xl sm:p-5">
            <h2 className="text-lg font-bold text-slate-900">Head of family contact</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">Provide WhatsApp active contact for the head of family. They will receive the full family packet later when WhatsApp broadcast is enabled.</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <ContactInput icon={<Mail className="h-5 w-5" />} label="Head email" type="email" value={headEmail} onChange={setHeadEmail} required />
              <ContactInput icon={<Phone className="h-5 w-5" />} label="Head WhatsApp active number" type="tel" value={headPhone} onChange={setHeadPhone} required />
            </div>
            {departureCities.length > 0 && (
              <DepartureCitySelect value={departureCity} cities={departureCities} onChange={setDepartureCity} className="mt-4" />
            )}
          </section>
          <Button type="submit" size="lg" className="h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700">
            Submit Family Details
          </Button>
        </form>
      </div>
    );
  }

  if (step === "SUCCESS") {
    const name = flowMode === "family" ? `${familyMembers.length} family members` : clientName;
    return (
      <CenteredShell>
        <div className="w-full max-w-md rounded-2xl border border-slate-100 bg-white p-8 text-center shadow-xl shadow-slate-200/50">
          <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-tr from-green-500 to-emerald-400 shadow-lg shadow-green-500/30">
            <CheckCircle2 className="h-10 w-10 text-white" />
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

          {step === "NAME_INPUT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <BackButton onClick={() => setStep("MODE_SELECT")} />
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
                            onClick={() => setActiveFamilyIndex(index)}
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
                      <ChoiceCard icon={<Camera className="h-6 w-6" />} title="Take a Photo" description="Use your device camera to scan the passport data page." onClick={() => setStep("CAMERA")} />
                      <UploadFileButton onClick={() => fileInputRef.current?.click()} />
                      <input ref={fileInputRef} type="file" className="hidden" accept="image/*" onChange={handleFileUpload} />
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
                    <ChoiceCard icon={<Camera className="h-6 w-6" />} title="Take a Photo" description="Use your device camera to scan the passport data page." onClick={() => setStep("CAMERA")} />
                    <UploadFileButton onClick={() => fileInputRef.current?.click()} />
                    <input ref={fileInputRef} type="file" className="hidden" accept="image/*" onChange={handleFileUpload} />
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
    submission: null,
    reviewFields: {},
  };
}

function createFamilyMembers(count: number) {
  return Array.from({ length: count }, (_, index) => createFamilyMember(index));
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

function UploadFileButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-start gap-3 rounded-2xl border-2 border-slate-100 bg-white p-4 text-left shadow-sm transition-all active:scale-[0.99] hover:border-blue-600 hover:bg-blue-50/50 hover:shadow-md sm:gap-4 sm:p-5"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600 transition-colors group-hover:bg-blue-600 group-hover:text-white sm:h-12 sm:w-12">
        <Upload className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <h4 className="text-base font-bold text-slate-900 transition-colors group-hover:text-blue-900">Upload File</h4>
        <p className="mt-1 text-sm leading-5 text-slate-500">Choose an existing photo from your gallery.</p>
      </div>
    </button>
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

function ContactInput({ icon, label, type, value, onChange, required = false }: { icon: ReactNode; label: string; type: string; value: string; onChange: (value: string) => void; required?: boolean }) {
  return (
    <label className="block min-w-0 space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <div className="relative min-w-0">
        <span className="absolute left-3 top-3 text-slate-400">{icon}</span>
        <Input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-10 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white" required={required} />
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

function DepartureCitySelect({ value, cities, onChange, className = "" }: { value: string; cities: string[]; onChange: (value: string) => void; className?: string }) {
  return (
    <label className={`block min-w-0 space-y-1.5 ${className}`}>
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Departure City</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100" required>
        <option value="">Select your departure city</option>
        {cities.map((city) => <option key={city} value={city}>{city}</option>)}
      </select>
    </label>
  );
}

function ReviewLayout({ title, description, image, fields, onBack, children }: { title: string; description: string; image: string | null; fields: ExtractedPassportFields | null; onBack: () => void; children: ReactNode }) {
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
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="relative w-full">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={image} alt="Uploaded passport" className="block h-auto w-full" />
                <PassportRoiOverlays fields={fields} />
              </div>
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
  return <div className="mb-5 rounded-xl border border-red-100 bg-red-50 p-4 text-sm font-medium text-red-700">{message}</div>;
}

function ReviewFields({ fields, onChange }: { fields: Record<string, string>; onChange: (key: string, value: string) => void }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {REVIEW_FIELDS.map((key) => (
        <label key={key} className="space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{toLabel(key)}</span>
          <Input value={fields[key] ?? ""} onChange={(event) => onChange(key, event.target.value)} placeholder="Not extracted" className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-slate-50 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white" />
        </label>
      ))}
    </div>
  );
}

function CenteredLoader() {
  return (
    <CenteredShell>
      <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
    </CenteredShell>
  );
}

function CenteredShell({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">{children}</div>;
}

function ProcessingScreen({ title, description, progress }: { title: string; description: string; progress?: number | null }) {
  return (
    <CenteredShell>
      <div className="flex w-full max-w-md flex-col items-center justify-center text-center">
        <div className="relative mb-8">
          <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl"></div>
          <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
            <Loader2 className="h-10 w-10 animate-spin text-white" />
          </div>
        </div>
        <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">{title}</h2>
        <p className="mx-auto max-w-xs text-slate-500">{description}</p>
        {typeof progress === "number" && (
          <div className="mt-6 h-2 w-full max-w-xs overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-blue-600 transition-all duration-500" style={{ width: `${Math.max(8, Math.min(100, Math.round(progress * 100)))}%` }} />
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
    if (!next[key]?.trim() && typeof value === "string" && value.trim()) next[key] = value;
    return next;
  }, { ...current });
}

function hasMissingRequiredFields(fields: Record<string, string>) {
  return REVIEW_FIELDS.some((key) => !fields[key]?.trim());
}

function validateReviewFields(fields: Record<string, string>) {
  return !hasMissingRequiredFields(fields);
}

function cleanReviewFields(fields: Record<string, string>) {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
}

function toLabel(value: string) {
  if (value === "given_names") return "Name";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function isExtractionComplete(submission: PassportSubmission) {
  return submission.status === "review_required" && Boolean(submission.extracted_fields);
}

function sleep(delayMs: number) {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

function stageLabel(stage: string) {
  return stage.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
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
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? "Could not submit reviewed details. Please check the contact details.";
  }
  return "Could not submit reviewed details. Please try again.";
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && !(error instanceof AxiosError)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? fallback;
  }
  return fallback;
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
