import { Send } from "lucide-react";
import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import { Button } from "@/components/ui";
import { DialogFrame, ErrorBanner } from "../components/whatsapp-dialog-ui";
import type { ComposerController } from "./message-composer";

interface ReviewDialogProps {
  model: ComposerController;
  checkedHistory: boolean;
  setCheckedHistory: (checked: boolean) => void;
}
export function MessageComposerReviewDialog({ model, checkedHistory, setCheckedHistory }: ReviewDialogProps) {
  const definition = model.definition;
  return (
    <DialogFrame
      title="Review and send"
      description={`${definition.label} · ${model.group.name}`}
      onClose={() => model.setReviewing(false)}
      isBusy={model.pending}
    >
      <div className="space-y-5">
        <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3">
          <span className="text-sm text-slate-600">Selected audience</span>
          <strong className="text-sm text-slate-900">
            {model.reviewedCount} WhatsApp numbers
          </strong>
        </div>
        <div className="max-h-72 overflow-y-auto rounded-xl bg-emerald-50 p-5 text-sm leading-6 text-slate-800 whitespace-pre-wrap [overflow-wrap:anywhere]">
          {model.reviewedMessage}
        </div>
        <p className="text-xs leading-5 text-slate-500">
          {model.recovery
            ? "This checks the saved send shown above using the same request."
            : "Each selected number receives a private WhatsApp message. This send will have its own delivery report."}
        </p>
        {model.error && <ErrorBanner message={model.error} />}
        {model.uncertain && (
          <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <Link
              href={ROUTES.dashboard.whatsappBroadcastHistory(
                model.group.id,
              )}
              target="_blank"
              className="font-medium underline"
            >
              Open delivery history
            </Link>
            <label className="flex items-start gap-2 text-xs leading-5">
              <input
                type="checkbox"
                checked={checkedHistory}
                onChange={(event) =>
                  setCheckedHistory(event.target.checked)
                }
                className="mt-1 accent-blue-600"
              />
              I checked the earlier send and want to prepare a separate
              message.
            </label>
            <Button
              variant="secondary"
              disabled={!checkedHistory}
              onClick={model.startSeparateMessage}
            >
              Prepare a separate message
            </Button>
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button
            variant="secondary"
            onClick={() => model.setReviewing(false)}
            disabled={model.pending}
          >
            Back to editing
          </Button>
          <Button
            disabled={
              Boolean(model.uncertain) || (!model.recovery && !model.ready)
            }
            isLoading={model.pending}
            onClick={() => void model.send(Boolean(model.recovery))}
          >
            <Send className="h-4 w-4" />
            {model.recovery
              ? "Check send status"
              : `Send ${model.count ?? model.selected.length} messages`}
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}
