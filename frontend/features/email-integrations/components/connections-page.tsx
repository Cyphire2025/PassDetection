"use client";

import {
  Mail,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
} from "@/components/ui";
import { formatDateTime, formatRelativeTime } from "@/lib/utils/format";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { EmailConnection } from "../types";
import {
  useAuthorizeEmailProvider,
  useEmailConnections,
  useEmailIntegrationStatus,
  useEmailIntegrationSummary,
  usePauseEmailConnection,
  useRemoveEmailConnection,
  useResumeEmailConnection,
  useSyncEmailConnection,
  useUpdateEmailAiSettings,
} from "../hooks/use-email-integrations";
import {
  cleanEmailOAuthCallbackUrl,
  isSafeOAuthAuthorizationUrl,
  readEmailOAuthCallback,
} from "../utils/email-integrations";
import {
  Definition,
  EmailCardSkeletons,
  EmailDialog,
  EmailNotice,
  EmailQueryError,
  EmailStatusBadge,
} from "./email-integrations-ui";
import { EmailAiRolloutControl } from "./email-ai-rollout-control";

const SUMMARY_METRICS = [
  ["connected_accounts", "Connected accounts"],
  ["relevant_emails_today", "Relevant emails today"],
  ["documents_retrieved_today", "Documents retrieved today"],
  ["automatically_matched_today", "Automatically matched today"],
  ["revisions_detected_today", "Revisions detected today"],
  ["pending_review", "Pending review"],
  ["retrieval_failures_today", "Retrieval failures today"],
] as const;

type Notice = {
  tone: "success" | "error" | "warning" | "info";
  message: string;
};

type AiSettingsTarget = {
  connection: EmailConnection;
  enabled: boolean;
};

export function EmailConnectionsPage() {
  const role = useAuthStore(selectUserRole);
  const status = useEmailIntegrationStatus();
  const connections = useEmailConnections();
  const summary = useEmailIntegrationSummary();
  const authorize = useAuthorizeEmailProvider();
  const sync = useSyncEmailConnection();
  const pause = usePauseEmailConnection();
  const resume = useResumeEmailConnection();
  const removeConnection = useRemoveEmailConnection();
  const updateAiSettings = useUpdateEmailAiSettings();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [removeTarget, setRemoveTarget] =
    useState<EmailConnection | null>(null);
  const [removalConfirmation, setRemovalConfirmation] = useState("");
  const [aiSettingsTarget, setAiSettingsTarget] =
    useState<AiSettingsTarget | null>(null);
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const callbackNotice = readEmailOAuthCallback(window.location.search);
    const noticeFrame = callbackNotice
      ? window.requestAnimationFrame(() => setNotice(callbackNotice))
      : null;

    const cleanedUrl = cleanEmailOAuthCallbackUrl(new URL(window.location.href));
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (cleanedUrl !== currentUrl) {
      window.history.replaceState(window.history.state, "", cleanedUrl);
    }
    return () => {
      if (noticeFrame !== null) window.cancelAnimationFrame(noticeFrame);
    };
  }, []);

  const gmailProvider = useMemo(
    () => status.data?.providers.find((provider) => provider.provider === "gmail"),
    [status.data],
  );
  const canConnectGmail =
    status.data?.enabled === true && gmailProvider?.configured === true;
  const outlookProvider = useMemo(
    () => status.data?.providers.find((provider) => provider.provider === "outlook"),
    [status.data],
  );
  const canConnectOutlook =
    status.data?.enabled === true && outlookProvider?.configured === true;
  const anyConnectionMutation =
    sync.isPending
    || pause.isPending
    || resume.isPending
    || removeConnection.isPending
    || updateAiSettings.isPending
    || authorize.isPending;

  function startAuthorization(
    provider: "gmail" | "outlook",
    connectionId?: string,
  ) {
    setNotice(null);
    setActiveConnectionId(connectionId ?? `new-${provider}`);
    authorize.mutate({ provider, connectionId }, {
      onSuccess: ({ authorization_url: authorizationUrl }) => {
        if (!isSafeOAuthAuthorizationUrl(authorizationUrl)) {
          setNotice({
            tone: "error",
            message:
              "The email provider returned an invalid authorization address. Please contact support.",
          });
          setActiveConnectionId(null);
          return;
        }
        window.location.assign(authorizationUrl);
      },
      onError: () => {
        setNotice({
          tone: "error",
          message: `${provider === "outlook" ? "Microsoft Outlook" : "Gmail"} authorization could not be started. Please try again.`,
        });
        setActiveConnectionId(null);
      },
    });
  }

  function runConnectionAction(
    action: "sync" | "pause" | "resume",
    connectionId: string,
  ) {
    setNotice(null);
    setActiveConnectionId(connectionId);
    const mutation =
      action === "sync" ? sync : action === "pause" ? pause : resume;
    mutation.mutate(connectionId, {
      onSuccess: () => {
        setNotice({
          tone: "success",
          message:
            action === "sync"
              ? "Manual synchronization was queued."
              : action === "pause"
                ? "Inbox monitoring was paused."
                : "Inbox monitoring was resumed.",
        });
        setActiveConnectionId(null);
      },
      onError: () => {
        setNotice({
          tone: "error",
          message: `The connection could not be ${action === "sync" ? "synchronized" : `${action}d`}. Please try again.`,
        });
        setActiveConnectionId(null);
      },
    });
  }

  function openAiSettings(connection: EmailConnection, enabled: boolean) {
    setNotice(null);
    updateAiSettings.reset();
    setAiSettingsTarget({ connection, enabled });
  }

  function closeAiSettings() {
    if (updateAiSettings.isPending) return;
    setAiSettingsTarget(null);
    updateAiSettings.reset();
  }

  function confirmAiSettings() {
    if (!aiSettingsTarget) return;
    const { connection, enabled } = aiSettingsTarget;
    setActiveConnectionId(connection.id);
    updateAiSettings.mutate(
      { connectionId: connection.id, enabled },
      {
        onSuccess: (response) => {
          setActiveConnectionId(null);
          setAiSettingsTarget(null);
          setNotice({
            tone:
              response.enabled && !response.effective_enabled
                ? "info"
                : "success",
            message: response.enabled
              ? `${response.message} Prepared drafts remain unsent, and deployment policy may still keep analysis in shadow mode.`
              : response.message,
          });
        },
        onError: () => {
          setActiveConnectionId(null);
        },
      },
    );
  }

  function openRemoval(connection: EmailConnection) {
    setNotice(null);
    removeConnection.reset();
    setRemovalConfirmation("");
    setRemoveTarget(connection);
  }

  function closeRemoval() {
    if (removeConnection.isPending) return;
    setRemoveTarget(null);
    setRemovalConfirmation("");
    removeConnection.reset();
  }

  function confirmRemoval() {
    if (!removeTarget) return;
    const connectionId = removeTarget.id;
    setActiveConnectionId(connectionId);
    removeConnection.mutate(
      {
        connectionId,
        confirmationEmail: removalConfirmation,
      },
      {
        onSuccess: (response) => {
          setRemoveTarget(null);
          setRemovalConfirmation("");
          setActiveConnectionId(null);
          setNotice({
            tone: response.storage_cleanup_pending ? "warning" : "success",
            message: response.storage_cleanup_pending
              ? "The account and visible integration data were removed. Final cleanup of unreferenced stored files will complete automatically."
              : response.message,
          });
        },
        onError: () => {
          setActiveConnectionId(null);
        },
      },
    );
  }

  const removalEmailMatches =
    removeTarget !== null &&
    removalConfirmation.trim().toLowerCase() ===
      removeTarget.email_address.trim().toLowerCase();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-950">
            Email Integrations
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Connect business inboxes for secure, server-side travel document
            monitoring and processing.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            leftIcon={<Mail className="h-4 w-4" aria-hidden="true" />}
            isLoading={authorize.isPending && activeConnectionId === "new-gmail"}
            disabled={!canConnectGmail || anyConnectionMutation}
            onClick={() => startAuthorization("gmail")}
          >
            Connect Gmail
          </Button>
          <Button
            type="button"
            variant="secondary"
            leftIcon={<Mail className="h-4 w-4" aria-hidden="true" />}
            isLoading={authorize.isPending && activeConnectionId === "new-outlook"}
            disabled={!canConnectOutlook || anyConnectionMutation}
            onClick={() => startAuthorization("outlook")}
          >
            Connect Outlook
          </Button>
        </div>
      </div>

      {notice && <EmailNotice tone={notice.tone}>{notice.message}</EmailNotice>}

      {status.isError && (
        <EmailQueryError
          title="Email provider availability could not be checked."
          onRetry={() => void status.refetch()}
        />
      )}
      {status.data && !status.data.enabled && (
        <EmailNotice tone="warning">
          Email integrations are not enabled for this environment.
        </EmailNotice>
      )}
      {status.data?.enabled && gmailProvider && !gmailProvider.configured && (
        <EmailNotice tone="warning">
          Gmail authorization has not been configured by an administrator.
        </EmailNotice>
      )}
      {status.data?.enabled && outlookProvider && !outlookProvider.configured && (
        <EmailNotice tone="warning">
          Microsoft Outlook authorization has not been configured by an
          administrator.
        </EmailNotice>
      )}
      {status.data?.enabled && !status.data.sync_enabled && (
        <EmailNotice tone="warning">
          Inbox monitoring is temporarily disabled. Existing connections will
          not synchronize until it is enabled again.
        </EmailNotice>
      )}

      {role === "super_admin" && <EmailAiRolloutControl />}

      <section aria-labelledby="email-summary-heading">
        <h2
          id="email-summary-heading"
          className="mb-3 text-base font-semibold text-slate-900"
        >
          Today&apos;s email operations
        </h2>
        {summary.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 7 }, (_, index) => (
              <Skeleton key={index} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : summary.isError ? (
          <EmailQueryError
            title="Email processing totals could not be loaded."
            onRetry={() => void summary.refetch()}
          />
        ) : summary.data ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {SUMMARY_METRICS.map(([key, label]) => (
              <Card key={key}>
                <CardContent className="p-4">
                  <p className="text-2xl font-bold text-slate-950">
                    {summary.data[key].toLocaleString()}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">{label}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="connected-inboxes-heading" className="space-y-3">
        <div>
          <h2
            id="connected-inboxes-heading"
            className="text-base font-semibold text-slate-900"
          >
            Connected inboxes
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Monitoring continues on the server even when staff are signed out.
          </p>
        </div>

        {connections.isLoading ? (
          <EmailCardSkeletons count={2} />
        ) : connections.isError ? (
          <EmailQueryError
            title="Connected email accounts could not be loaded."
            onRetry={() => void connections.refetch()}
          />
        ) : connections.data?.length ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {connections.data.map((connection) => {
              const actions = new Set(connection.allowed_actions);
              const isBusy =
                anyConnectionMutation && activeConnectionId === connection.id;
              return (
                <Card key={connection.id}>
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
                      className={`rounded-lg border p-4 ${
                        connection.ai_processing_enabled
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
            })}
          </div>
        ) : (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center px-6 py-12 text-center">
              <span className="rounded-full bg-blue-50 p-3 text-blue-700">
                <Mail className="h-6 w-6" aria-hidden="true" />
              </span>
              <h3 className="mt-4 font-semibold text-slate-900">
                No email accounts connected
              </h3>
              <p className="mt-1 max-w-lg text-sm text-slate-600">
                Connect a supported Gmail or Microsoft Outlook account to begin
                background monitoring.
              </p>
            </CardContent>
          </Card>
        )}
      </section>

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
    </div>
  );
}
