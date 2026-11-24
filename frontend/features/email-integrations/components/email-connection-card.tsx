import { Pause, Play, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatDateTime, formatRelativeTime } from "@/lib/utils/format";
import type { EmailConnection } from "../types";
import type { EmailConnectionsController } from "../hooks/use-email-connections-controller";
import { Definition, EmailNotice, EmailStatusBadge } from "./email-integrations-ui";

export function EmailConnectionCard({ connection, controller }: {
  connection: EmailConnection;
  controller: EmailConnectionsController;
}) {
  const { anyConnectionMutation, activeConnectionId, status, updateAiSettings,
    sync, pause, resume, authorize, canConnectGmail, canConnectOutlook,
    openAiSettings, openRemoval, runConnectionAction, startAuthorization } = controller;
  const actions = new Set(connection.allowed_actions);
  const isBusy = anyConnectionMutation && activeConnectionId === connection.id;
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 p-5 pb-3">
        <div className="min-w-0">
          <CardTitle className="truncate">
            {connection.email_address}
          </CardTitle>
        </div>
        <EmailStatusBadge status={connection.status} />
      </CardHeader>
      <CardContent className="space-y-4 p-5 pt-0">
        <dl className="grid gap-4 sm:grid-cols-2">
          <Definition term="Provider">
            {connection.provider === "gmail"
              ? "Gmail"
              : "Microsoft Outlook"}
          </Definition>
          <Definition term="Last successful sync">
            <span title={formatDateTime(connection.last_successful_sync_at)}>
              {formatRelativeTime(connection.last_successful_sync_at)}
            </span>
          </Definition>
          <Definition term="Last sync attempt">
            {formatDateTime(connection.last_sync_attempt_at)}
          </Definition>
        </dl>

        <div
          className={`rounded-lg border p-4 ${connection.ai_processing_enabled
            ? "border-blue-200 bg-blue-50/60"
            : "border-slate-200 bg-slate-50"
            }`}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Sparkles
                  className="h-4 w-4 text-blue-700"
                  aria-hidden="true"
                />
                <h3 className="text-sm font-semibold text-slate-900">
                  Travel AI assistance
                </h3>
                <Badge
                  variant={
                    connection.ai_processing_enabled
                      ? "secondary"
                      : "outline"
                  }
                >
                  {connection.ai_processing_enabled
                    ? connection.ai_effective_enabled
                      ? "Active"
                      : "Opted in · waiting"
                    : "Off"}
                </Badge>
              </div>
              <p
                id={`email-ai-description-${connection.id}`}
                className="mt-2 text-xs leading-5 text-slate-600"
              >
                {connection.ai_processing_enabled
                  ? connection.ai_effective_enabled
                    ? "New relevant travel email can be analyzed for deadlines, risks, prepared actions, and drafts."
                    : "Your preference is saved, but an organization, account, deployment, or mailbox safety control is keeping analysis inactive."
                  : "Opt in to analyze new relevant travel email from this mailbox."}{" "}
                Prepared drafts remain unsent. Deployment policy may
                still keep analysis in shadow mode.
              </p>
              {connection.ai_processing_enabled
                && status.data
                && !status.data.ai_notifications_enabled && (
                  <p className="mt-1 text-xs text-slate-500">
                    AI bell notifications are currently off at the
                    deployment level.
                  </p>
                )}
            </div>
            <Button
              type="button"
              size="sm"
              variant={
                connection.ai_processing_enabled
                  ? "secondary"
                  : "primary"
              }
              className="shrink-0"
              aria-describedby={`email-ai-description-${connection.id}`}
              isLoading={isBusy && updateAiSettings.isPending}
              disabled={
                anyConnectionMutation
                || connection.status === "disconnecting"
                || connection.status === "disconnected"
              }
              onClick={() =>
                openAiSettings(
                  connection,
                  !connection.ai_processing_enabled,
                )
              }
            >
              {connection.ai_processing_enabled
                ? "Turn off AI"
                : "Enable AI assistance"}
            </Button>
          </div>
        </div>

        {connection.last_error_message && (
          <EmailNotice tone="error">
            {connection.last_error_message.slice(0, 300)}
          </EmailNotice>
        )}

        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          {actions.has("sync") && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              leftIcon={
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              }
              isLoading={isBusy && sync.isPending}
              disabled={anyConnectionMutation}
              onClick={() => runConnectionAction("sync", connection.id)}
            >
              Sync now
            </Button>
          )}
          {actions.has("pause") && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              leftIcon={<Pause className="h-3.5 w-3.5" aria-hidden="true" />}
              isLoading={isBusy && pause.isPending}
              disabled={anyConnectionMutation}
              onClick={() => runConnectionAction("pause", connection.id)}
            >
              Pause
            </Button>
          )}
          {actions.has("resume") && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              leftIcon={<Play className="h-3.5 w-3.5" aria-hidden="true" />}
              isLoading={isBusy && resume.isPending}
              disabled={anyConnectionMutation}
              onClick={() => runConnectionAction("resume", connection.id)}
            >
              Resume
            </Button>
          )}
          {actions.has("reconnect") && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              isLoading={isBusy && authorize.isPending}
              disabled={
                anyConnectionMutation
                || (connection.provider === "gmail"
                  ? !canConnectGmail
                  : !canConnectOutlook)
              }
              onClick={() =>
                startAuthorization(connection.provider, connection.id)
              }
            >
              Reconnect
            </Button>
          )}
          {actions.has("remove") && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="text-red-700 hover:bg-red-50 hover:text-red-800"
              leftIcon={<Trash2 className="h-3.5 w-3.5" aria-hidden="true" />}
              disabled={anyConnectionMutation}
              onClick={() => openRemoval(connection)}
            >
              Remove account
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
