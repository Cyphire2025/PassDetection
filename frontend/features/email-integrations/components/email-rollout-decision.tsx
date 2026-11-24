import { Button } from "@/components/ui";
import type { EmailRolloutController } from "../hooks/use-email-rollout-controller";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";
import { scopeSingular, readRolloutError } from "./email-rollout-model";

export function EmailRolloutDecision({ controller }: { controller: EmailRolloutController; }) {
  const { decision, updatePolicy, closeDecision, saveDecision } = controller;
  return (
    <>
      {decision && (
        <EmailDialog
          title={`${decision.enabled ? "Allow" : "Pause"} AI for ${decision.target.label}?`}
          description={`This changes the direct rollout rule for one ${scopeSingular(decision.target.scope_type)}.`}
          isBusy={updatePolicy.isPending}
          onClose={closeDecision}
        >
          <div className="space-y-4">
            <p className="text-sm leading-6 text-slate-700">
              {decision.enabled
                ? "This level will allow AI, but any global or parent pause will continue to win."
                : "This level and everything below it will remain paused until it is allowed again."}
            </p>
            <EmailNotice tone="info">
              Mailbox owners must still opt in separately. This rollout choice
              does not send messages, change provider permissions, or delete
              existing intelligence.
            </EmailNotice>
            {updatePolicy.isError && (
              <EmailNotice tone="error">
                {readRolloutError(updatePolicy.error)}
              </EmailNotice>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="secondary"
                disabled={updatePolicy.isPending}
                onClick={closeDecision}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant={decision.enabled ? "primary" : "danger"}
                isLoading={updatePolicy.isPending}
                onClick={saveDecision}
              >
                {decision.enabled ? "Allow" : "Pause"}
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
    </>
  );
}
