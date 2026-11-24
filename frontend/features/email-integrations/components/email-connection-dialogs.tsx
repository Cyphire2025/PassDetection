import { Button, Input } from "@/components/ui";
import type { EmailConnectionsController } from "../hooks/use-email-connections-controller";
import { EmailDialog, EmailNotice } from "./email-integrations-ui";

export function EmailConnectionDialogs({ controller }: { controller: EmailConnectionsController; }) {
  const { aiSettingsTarget, updateAiSettings, closeAiSettings, status,
    confirmAiSettings, removeTarget, removeConnection, closeRemoval,
    removalConfirmation, setRemovalConfirmation, removalEmailMatches, confirmRemoval } = controller;
  return (
    <>
      {aiSettingsTarget && (
        <EmailDialog
          title={
            aiSettingsTarget.enabled
              ? "Enable AI assistance for this mailbox?"
              : "Turn off AI assistance for this mailbox?"
          }
          description={`${aiSettingsTarget.connection.email_address} remains a read-only connected account.`}
          isBusy={updateAiSettings.isPending}
          onClose={closeAiSettings}
        >
          <div className="space-y-4">
            {aiSettingsTarget.enabled ? (
              <>
                <p className="text-sm leading-6 text-slate-700">
                  New relevant travel email can be analyzed for operational
                  summaries, deadlines, risks, safe proposals, and prepared
                  reply drafts.
                </p>
                <EmailNotice tone="info">
                  Prepared drafts remain unsent. Enabling this preference does
                  not grant mailbox write access, and deployment policy may
                  still keep analysis in shadow mode.
                </EmailNotice>
                {status.data && !status.data.ai_enabled && (
                  <EmailNotice tone="warning">
                    Deployment-level AI is currently off. Your opt-in will be
                    saved, but analysis will not become effective until an
                    administrator enables the service.
                  </EmailNotice>
                )}
              </>
            ) : (
              <p className="text-sm leading-6 text-slate-700">
                New AI analysis will stop for this mailbox. Existing inbox
                activity and audit history will remain available.
              </p>
            )}
            {updateAiSettings.isError && (
              <EmailNotice tone="error">
                The AI preference could not be confirmed. The current mailbox
                setting is being refreshed; check it before trying again.
              </EmailNotice>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="secondary"
                disabled={updateAiSettings.isPending}
                onClick={closeAiSettings}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant={aiSettingsTarget.enabled ? "primary" : "danger"}
                isLoading={updateAiSettings.isPending}
                onClick={confirmAiSettings}
              >
                {aiSettingsTarget.enabled
                  ? "Enable AI assistance"
                  : "Turn off AI"}
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}

      {removeTarget && (
        <EmailDialog
          title="Permanently remove email account?"
          description={`This permanently removes ${removeTarget.email_address} and the integration data attributable to it.`}
          isBusy={removeConnection.isPending}
          onClose={closeRemoval}
        >
          <div className="space-y-4">
            <EmailNotice tone="warning">
              This cannot be undone. It removes stored credentials, synced
              messages, activity, review items, AI analyses, notifications,
              retrieved attachments, and saved travel documents created only
              from this mailbox. Other connected accounts, passengers, groups,
              and manually uploaded documents are not changed.
            </EmailNotice>
            <div>
              <label
                className="mb-1.5 block text-sm font-medium text-slate-800"
                htmlFor="email-removal-confirmation"
              >
                Type {removeTarget.email_address} to confirm
              </label>
              <Input
                id="email-removal-confirmation"
                type="email"
                autoComplete="off"
                spellCheck={false}
                value={removalConfirmation}
                disabled={removeConnection.isPending}
                onChange={(event) => setRemovalConfirmation(event.target.value)}
              />
            </div>
            {removeConnection.isError && (
              <EmailNotice tone="error">
                The account could not be removed safely. No partial database
                cleanup was performed; retry after checking the connection.
              </EmailNotice>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="secondary"
                disabled={removeConnection.isPending}
                onClick={closeRemoval}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                isLoading={removeConnection.isPending}
                disabled={!removalEmailMatches || removeConnection.isPending}
                onClick={confirmRemoval}
              >
                Permanently remove account
              </Button>
            </div>
          </div>
        </EmailDialog>
      )}
    </>
  );
}
