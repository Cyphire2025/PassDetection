import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiErrorCode, apiErrorStatus } from "@/lib/api/error-status";
import { CenteredShell } from "./upload-flow-shell";

export function UploadLinkErrorScreen({ error, onRetry, isRetrying }: {
  error: unknown;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  const closed = apiErrorCode(error) === "CLIENT_GROUP_CLOSED";
  const terminal = closed || [400, 401, 403, 404, 410, 422].includes(apiErrorStatus(error) ?? 0);
  const title = closed ? "This link is closed." : terminal ? "Link Unavailable" : "Unable to open this link";
  const message = closed
    ? "This group is no longer accepting submissions. Please contact Global Connect Travels if you need it reopened."
    : terminal
      ? "This group link is not available. Please contact Global Connect Travels for a working link."
      : "We could not reach the server. Check your connection and try again. Your saved upload has not been discarded.";
  return (
    <CenteredShell>
      <div role="alert" aria-labelledby="upload-link-unavailable-title" className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-8 text-center shadow-lg">
        <AlertCircle className="mx-auto mb-4 h-10 w-10 text-red-600" aria-hidden="true" />
        <h2 id="upload-link-unavailable-title" className="mb-2 text-2xl font-bold tracking-tight text-slate-900">{title}</h2>
        <p className="text-base text-slate-600">{message}</p>
        <Button className="mt-5" onClick={onRetry} isLoading={isRetrying}>{terminal ? "Check again" : "Retry"}</Button>
      </div>
    </CenteredShell>
  );
}
