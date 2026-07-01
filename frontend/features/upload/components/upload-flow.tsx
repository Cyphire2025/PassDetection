"use client";

import { useRef, useState } from "react";
import { AxiosError } from "axios";
import Image from "next/image";
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  Camera,
  ChevronRight,
  User,
  Mail,
  Phone,
} from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import { useSubmitClientPassportReview, useUploadPassport } from "../hooks/use-upload";
import { uploadApi } from "../api/upload.api";
import { normalizePassportFile } from "../services/passport-perspective-correction";
import { SmartCamera } from "./smart-camera";

interface UploadFlowProps {
  token: string;
}

type Step = "NAME_INPUT" | "METHOD_SELECT" | "CAMERA" | "UPLOADING" | "REVIEW" | "SUBMITTING" | "SUCCESS";

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

export function UploadFlow({ token }: UploadFlowProps) {
  const { data: group, isLoading, error } = useUploadLinkByToken(token);
  const { mutateAsync: uploadPassport } = useUploadPassport();
  const { mutateAsync: submitClientReview } = useSubmitClientPassportReview();

  const [step, setStep] = useState<Step>("NAME_INPUT");
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [submission, setSubmission] = useState<PassportSubmission | null>(null);
  const [reviewFields, setReviewFields] = useState<Record<string, string>>({});
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [processingProgress, setProcessingProgress] = useState<number | null>(null);
  const [processingStage, setProcessingStage] = useState<string>("Uploading securely");
  const [isPreparingFile, setIsPreparingFile] = useState(false);
  const nativeCameraInputRef = useRef<HTMLInputElement>(null);

  const handleNameSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (clientName.trim().length > 1) {
      setStep("METHOD_SELECT");
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      await processUpload(event.target.files[0]);
      event.target.value = "";
    }
  };

  const handleCameraCapture = async (file: File) => {
    await processUpload(file);
  };

  const openDeviceCamera = () => {
    const supportsLiveCamera = window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia);
    if (supportsLiveCamera) {
      setStep("CAMERA");
      return;
    }

    nativeCameraInputRef.current?.click();
  };

  const processUpload = async (file: File) => {
    try {
      setUploadError(null);
      setIsPreparingFile(true);
      const normalized = await normalizePassportFile(file);
      setIsPreparingFile(false);
      setStep("UPLOADING");
      const result = await uploadPassport({ token, client_name: clientName, file: normalized.file });
      const completed = isExtractionComplete(result)
        ? result
        : await waitForExtraction(result);
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

  const handleScanAgain = () => {
    setSubmission(null);
    setReviewFields({});
    setUploadError(null);
    setStep("METHOD_SELECT");
  };

  const handleFinalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!submission) return;

    const confirmedFields = Object.fromEntries(
      Object.entries(reviewFields)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value),
    );
    if (Object.keys(confirmedFields).length === 0) {
      setUploadError("Please verify and enter the passport details before submitting.");
      return;
    }
    if (hasMissingRequiredFields(reviewFields)) {
      setUploadError("Please fill all passport fields before submitting. You can type corrections manually or scan again.");
      return;
    }

    try {
      setUploadError(null);
      setProcessingProgress(null);
      setProcessingStage("Uploading securely");
      setStep("SUBMITTING");
      await submitClientReview({
        submissionId: submission.id,
        group_token: token,
        confirmed_fields: confirmedFields,
        client_email: clientEmail,
        client_phone: clientPhone,
      });
      setStep("SUCCESS");
    } catch (error: unknown) {
      const message = error instanceof AxiosError
        ? (error.response?.data as { detail?: string } | undefined)?.detail
        : undefined;
      setUploadError(message ?? "Could not submit reviewed details. Please check your email and phone number.");
      setStep("REVIEW");
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error || !group) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-8 text-center shadow-lg">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
            <AlertCircle className="h-7 w-7 text-red-600" />
          </div>
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Link Unavailable</h2>
          <p className="text-base text-slate-500">
            This secure group link is invalid, closed, or expired.
          </p>
        </div>
      </div>
    );
  }

  if (step === "CAMERA") {
    return <SmartCamera onCapture={handleCameraCapture} onCancel={() => setStep("METHOD_SELECT")} />;
  }

  if (isPreparingFile) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="flex w-full max-w-md flex-col items-center justify-center text-center">
          <div className="relative mb-8">
            <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl"></div>
            <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
              <Loader2 className="h-10 w-10 animate-spin text-white" />
            </div>
          </div>
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Preparing Passport Image</h2>
          <p className="mx-auto max-w-xs text-slate-500">
            Straightening the capture and optimizing it before secure upload.
          </p>
        </div>
      </div>
    );
  }

  if (step === "UPLOADING") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="flex w-full max-w-md flex-col items-center justify-center text-center">
          <div className="relative mb-8">
            <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl"></div>
            <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
              <Loader2 className="h-10 w-10 animate-spin text-white" />
            </div>
          </div>
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Processing Passport</h2>
          <p className="mx-auto max-w-xs text-slate-500">
            {processingStage}. Reading the passport details so you can verify them before final submission.
          </p>
          {typeof processingProgress === "number" && (
            <div className="mt-6 h-2 w-full max-w-xs overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-blue-600 transition-all duration-500"
                style={{ width: `${Math.max(8, Math.min(100, Math.round(processingProgress * 100)))}%` }}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (step === "SUBMITTING") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="flex w-full max-w-md flex-col items-center justify-center text-center">
          <div className="relative mb-8">
            <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl"></div>
            <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
              <Loader2 className="h-10 w-10 animate-spin text-white" />
            </div>
          </div>
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">Submitting Reviewed Details</h2>
          <p className="mx-auto max-w-xs text-slate-500">
            Sending the verified passport information to your travel agency.
          </p>
        </div>
      </div>
    );
  }

  if (step === "REVIEW" && submission) {
    return (
      <div className="min-h-screen bg-slate-50 px-4 py-6 font-sans sm:py-10">
        <div className="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="space-y-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">Verify Passport Details</h1>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Passport information is used for travel bookings and official documents. Please check every field carefully before submitting to avoid delays or corrections later.
              </p>
            </div>

            {submission.image_url ? (
              <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="relative min-h-[24rem] w-full">
                  <Image
                    src={submission.image_url}
                    alt="Uploaded passport"
                    fill
                    unoptimized
                    className="object-contain"
                  />
                </div>
              </div>
            ) : (
              <div className="flex h-80 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-400">
                Passport preview unavailable
              </div>
            )}
          </div>

          <form onSubmit={handleFinalSubmit} className="rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-6">
            <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>
                Please compare these details with the passport image. Submit only after confirming the information is correct.
              </p>
            </div>

            {uploadError && (
              <div className="mb-5 rounded-xl border border-red-100 bg-red-50 p-4 text-sm font-medium text-red-700">
                {uploadError}
              </div>
            )}

            {hasMissingRequiredFields(reviewFields) && (
              <div className="mb-5 rounded-xl border border-blue-100 bg-blue-50 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm font-medium text-blue-800">
                    Some fields were not read clearly. You can still correct them manually or scan again with better light.
                  </p>
                  <Button type="button" variant="secondary" size="sm" onClick={handleScanAgain}>
                    Scan Again
                  </Button>
                </div>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {REVIEW_FIELDS.map((key) => (
                <label key={key} className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{toLabel(key)}</span>
                  <Input
                    value={reviewFields[key] ?? ""}
                    onChange={(event) => handleReviewFieldChange(key, event.target.value)}
                    placeholder="Not extracted"
                    className="h-11 rounded-xl border-slate-200 bg-slate-50 text-base focus-visible:bg-white"
                  />
                </label>
              ))}
            </div>

            <div className="mt-6 border-t border-slate-100 pt-5">
              <h3 className="mb-3 text-base font-bold text-slate-900">Contact Details</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Email</span>
                  <div className="relative">
                    <Mail className="absolute left-3 top-3 h-5 w-5 text-slate-400" />
                    <Input
                      type="email"
                      value={clientEmail}
                      onChange={(event) => setClientEmail(event.target.value)}
                      className="h-11 rounded-xl border-slate-200 bg-slate-50 pl-10 text-base focus-visible:bg-white"
                      required
                    />
                  </div>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Phone Number</span>
                  <div className="relative">
                    <Phone className="absolute left-3 top-3 h-5 w-5 text-slate-400" />
                    <Input
                      type="tel"
                      value={clientPhone}
                      onChange={(event) => setClientPhone(event.target.value)}
                      className="h-11 rounded-xl border-slate-200 bg-slate-50 pl-10 text-base focus-visible:bg-white"
                      required
                    />
                  </div>
                </label>
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-500">
                Each email and phone number can submit passport details only once for this group.
              </p>
            </div>

            <Button
              type="submit"
              size="lg"
              className="mt-6 h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
            >
              Submit Verified Details
            </Button>
          </form>
        </div>
      </div>
    );
  }

  if (step === "SUCCESS") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-md rounded-2xl border border-slate-100 bg-white p-8 text-center shadow-xl shadow-slate-200/50">
          <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-tr from-green-500 to-emerald-400 shadow-lg shadow-green-500/30">
            <CheckCircle2 className="h-10 w-10 text-white" />
          </div>
          <h2 className="mb-3 text-3xl font-bold tracking-tight text-slate-900">Details Submitted</h2>
          <p className="mb-8 text-base leading-relaxed text-slate-500">
            Thank you, <span className="font-semibold text-slate-900">{clientName}</span>. Your reviewed passport details
            have been securely submitted to the <strong>{group.name}</strong> group.
          </p>
          <div className="rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm font-medium text-slate-500">
            You may now safely close this window.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 py-6 font-sans selection:bg-blue-100 selection:text-blue-900 sm:py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center sm:mb-10">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-600 shadow-lg shadow-blue-600/30 sm:mb-6 sm:h-14 sm:w-14">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <rect x="4" y="4" width="24" height="24" rx="3" fill="white" fillOpacity="0.2" />
              <rect x="8" y="10" width="16" height="2" rx="1" fill="white" />
              <rect x="8" y="14" width="12" height="2" rx="1" fill="white" />
              <rect x="8" y="18" width="16" height="2" rx="1" fill="white" />
            </svg>
          </div>
          <h1 className="mb-3 text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">Upload Passport</h1>
          <p className="mx-auto max-w-md text-sm leading-relaxed text-slate-500 sm:text-base">
            Your travel agency has requested passport details for
          </p>
          <div className="mt-2 inline-flex rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-600">
            {group.name}
          </div>
        </div>

        {uploadError && (
          <div className="animate-in fade-in slide-in-from-top-2 mb-6 flex items-start gap-3 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-700">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
            <span className="font-medium">{uploadError}</span>
          </div>
        )}

        <div className="relative overflow-hidden rounded-3xl border border-slate-100 bg-white p-5 shadow-xl shadow-slate-200/50 sm:p-8">
          {step === "NAME_INPUT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <h3 className="mb-2 text-xl font-bold text-slate-900">Who is uploading?</h3>
              <p className="mb-6 text-sm text-slate-500">Enter the full name as it appears on the passport.</p>

              <form onSubmit={handleNameSubmit} className="space-y-6">
                <div className="relative">
                  <User className="absolute left-4 top-3.5 h-5 w-5 text-slate-400" />
                  <Input
                    placeholder="e.g. John Doe"
                    value={clientName}
                    onChange={(event) => setClientName(event.target.value)}
                    className="h-12 rounded-xl border-slate-200 bg-slate-50 pl-12 text-base transition-colors focus-visible:bg-white focus-visible:ring-blue-600"
                    required
                    autoFocus
                  />
                </div>
                <Button
                  type="submit"
                  size="lg"
                  className="h-12 w-full rounded-xl bg-blue-600 text-base font-semibold shadow-md shadow-blue-600/20 hover:bg-blue-700"
                  disabled={clientName.trim().length < 2}
                >
                  Continue <ChevronRight className="ml-1 h-5 w-5" />
                </Button>
              </form>
            </div>
          )}

          {step === "METHOD_SELECT" && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="mb-6 flex items-center justify-between gap-4">
                <h3 className="text-xl font-bold text-slate-900">Upload Method</h3>
                <button
                  onClick={() => setStep("NAME_INPUT")}
                  className="text-sm font-medium text-blue-600 hover:text-blue-700 hover:underline"
                >
                  Edit Name
                </button>
              </div>

              <div className="space-y-4">
                <button
                  type="button"
                  onClick={openDeviceCamera}
                  className="group flex w-full items-start gap-4 rounded-2xl border-2 border-slate-100 bg-white p-4 text-left shadow-sm transition-all hover:border-blue-600 hover:bg-blue-50/50 hover:shadow-md sm:p-5"
                >
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600 transition-colors group-hover:bg-blue-600 group-hover:text-white sm:h-12 sm:w-12">
                    <Camera className="h-6 w-6" />
                  </div>
                  <div>
                    <h4 className="text-base font-bold text-slate-900 transition-colors group-hover:text-blue-900">Take a Photo</h4>
                    <p className="mt-1 text-sm text-slate-500">Use your device camera to scan the passport data page</p>
                  </div>
                </button>
                <input
                  ref={nativeCameraInputRef}
                  type="file"
                  className="hidden"
                  accept="image/*"
                  capture="environment"
                  onChange={handleFileUpload}
                />
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600 sm:p-5">
                  This secure client link accepts camera capture only.
                </div>
              </div>
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-xs font-medium text-slate-400 sm:mt-8">
          Protected by Enterprise-grade Encryption • End-to-End Secure
        </p>
      </div>
    </div>
  );
}

function getInitialReviewFields(fields: ExtractedPassportFields | null) {
  return REVIEW_FIELDS.reduce<Record<string, string>>((current, key) => {
    const value = fields?.[key];
    current[key] = typeof value === "string" ? value : "";
    return current;
  }, {});
}

function hasMissingRequiredFields(fields: Record<string, string>) {
  return REVIEW_FIELDS.some((key) => !fields[key]?.trim());
}

function toLabel(value: string) {
  if (value === "given_names") return "Name";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function isExtractionComplete(submission: PassportSubmission) {
  return submission.status === "review_required" && Boolean(submission.extracted_fields);
}

function sleep(delayMs: number) {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

function stageLabel(stage: string) {
  return stage
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && !(error instanceof AxiosError)) {
    return error.message;
  }
  if (error instanceof AxiosError) {
    const payload = error.response?.data as { detail?: string; error?: { message?: string } } | undefined;
    return payload?.detail ?? payload?.error?.message ?? fallback;
  }
  return fallback;
}
