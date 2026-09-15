import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { PassportSubmission } from "@/types/passport.types";
import { CenteredShell } from "./upload-flow-shell";
import type { FamilyMember, FlowMode } from "./upload-flow.types";

export function resolveUploadLinkFailure({ error, linkError, isLoading, hasGroup }: {
  error: unknown;
  linkError: unknown;
  isLoading: boolean;
  hasGroup: boolean;
}): { error: unknown } | null {
  if (error || linkError || (!isLoading && !hasGroup)) {
    return { error: linkError ?? error };
  }
  return null;
}

export function UploadRecoveryScreen({ error, onRetry }: {
  error: string | null;
  onRetry: () => void;
}) {
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
            {error
              ?? "Your saved progress could not be reached. It has not been replaced or submitted again."}
          </p>
        </div>
        <Button
          type="button"
          className="mt-6 h-11 w-full"
          onClick={onRetry}
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

export function UploadSuccessScreen({ flowMode, familyMembers, submission, clientName, groupName }: {
  flowMode: FlowMode | null;
  familyMembers: FamilyMember[];
  submission: PassportSubmission | null;
  clientName: string;
  groupName: string;
}) {
  const awaitingReview = flowMode === "family"
    ? familyMembers.some((member) => member.submission?.status === "needs_review")
    : submission?.status === "needs_review";
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
        <h2 className="mb-3 text-3xl font-bold tracking-tight text-slate-900">{awaitingReview ? "Submitted — awaiting staff review" : "Details Submitted"}</h2>
        <p className="mb-8 text-base leading-relaxed text-slate-500">
          Thank you. <span className="font-semibold text-slate-900">{name}</span> have been securely submitted to the <strong>{groupName}</strong> group.
        </p>
        {awaitingReview && <p className="mb-5 text-sm text-slate-600">Staff will check the saved passport images and details before approving the submissions that need review.</p>}
        <div className="rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm font-medium text-slate-500">You may now safely close this window.</div>
      </div>
    </CenteredShell>
  );
}
