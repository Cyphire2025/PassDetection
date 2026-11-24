import { CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui";

type DocumentSentStatusProps = {
  status: string;
  sentTo: string | null;
  sentAt: string | null;
  canResend: boolean;
  onResend: () => void;
};

export function DocumentSentStatus({
  status,
  sentTo,
  sentAt,
  canResend,
  onResend,
}: DocumentSentStatusProps) {
  if (status === "sent") {
    return (
      <div className="min-w-40">
        <Badge variant="success">Sent</Badge>
        <div className="mt-1 text-xs font-medium text-slate-700">
          {sentTo || "WhatsApp accepted"}
        </div>
        {sentAt && (
          <div className="mt-0.5 text-xs text-slate-500">
            {new Date(sentAt).toLocaleString()}
          </div>
        )}
        {canResend && (
          <button
            type="button"
            onClick={onResend}
            className="mt-2 text-xs font-semibold text-blue-700 hover:text-blue-800 hover:underline"
          >
            Resend explicitly
          </button>
        )}
      </div>
    );
  }
  if (status === "queued" || status === "processing") {
    return <Badge variant="outline">In progress</Badge>;
  }
  if (status === "delivery_unknown") {
    return <Badge variant="warning">Outcome unknown</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">Failed</Badge>;
  }
  return <Badge variant="outline">Not sent</Badge>;
}

export function MatchBadge({ status }: { status: string }) {
  if (status === "matched") {
    return (
      <Badge variant="success" dot>
        <CheckCircle2 className="h-3 w-3" />
        Matched
      </Badge>
    );
  }
  if (status === "no_document") {
    return (
      <Badge variant="outline" className="whitespace-nowrap">
        <XCircle className="h-3 w-3" />
        No document
      </Badge>
    );
  }
  if (status === "duplicate_document") {
    return <Badge variant="warning">Previously replaced</Badge>;
  }
  return (
    <Badge variant="warning" dot>
      Needs review
    </Badge>
  );
}
