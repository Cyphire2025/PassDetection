import { ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui";
import { ErrorBanner, readErrorMessage } from "../components/whatsapp-dialog-ui";
import type { ComposerController } from "./message-composer";

export function MessageComposerFeedback({ model }: { model: ComposerController }) {
  return (<>
    {model.eligible.length === 0 && (
      <ErrorBanner message="No recipients are currently eligible for this message. Check Recipients and Delivery history; welcome delivery must be confirmed before follow-ups." />
    )}
    {model.preview.error && (
      <div className="space-y-2">
        <ErrorBanner
          message={readErrorMessage(
            model.preview.error,
            "The preview could not be checked.",
          )}
        />
        <Button
          type="button"
          variant="secondary"
          onClick={() => void model.preview.refetch()}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh preview
        </Button>
      </div>
    )}
    {model.current && !model.preview.data?.template_name && (
      <ErrorBanner message="Configure an approved template for this message in Settings before sending." />
    )}
    {model.current &&
      Boolean(model.preview.data?.welcome_required_count) && (
        <ErrorBanner
          message={
            model.preview.data?.welcome_required_reason ||
            "Some selected numbers need a delivered welcome message first."
          }
        />
      )}
    {!model.group.recipient_opt_in_confirmed && (
      <ErrorBanner message="Recipient opt-in has not been recorded for this broadcast. Confirm it before sending." />
    )}
    <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/95 px-5 py-4 shadow-sm backdrop-blur-sm">
      <p aria-live="polite" className="text-xs text-slate-500">
        <strong className="font-semibold text-slate-900">
          {model.count === null
            ? "Checking audience…"
            : `${model.count.toLocaleString()} WhatsApp numbers ready`}
        </strong>
        {model.current &&
          (model.preview.data?.already_sent_count ?? 0) > 0 && (
            <span>
              {" "}
              · {model.preview.data?.already_sent_count} earlier recipients
              excluded
            </span>
          )}
      </p>
      <Button type="submit" disabled={!model.ready && !model.recovery}>
        {model.recovery ? "Check earlier send" : "Review message"}
        <ArrowRight className="h-4 w-4" />
      </Button>
    </div>
  </>);
}
