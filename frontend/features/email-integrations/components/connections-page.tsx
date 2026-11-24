"use client";

import { Mail } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";
import { useEmailConnectionsController } from "../hooks/use-email-connections-controller";
import { EmailAiRolloutControl } from "./email-ai-rollout-control";
import { EmailCardSkeletons, EmailNotice, EmailQueryError } from "./email-integrations-ui";
import { EmailConnectionCard } from "./email-connection-card";
import { EmailConnectionDialogs } from "./email-connection-dialogs";
import { EmailConnectionSummary } from "./email-connection-summary";

export function EmailConnectionsPage() {
  const controller = useEmailConnectionsController();
  const { role, status, connections, summary, authorize, notice, activeConnectionId,
    gmailProvider, outlookProvider, canConnectGmail, canConnectOutlook,
    anyConnectionMutation, startAuthorization } = controller;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-[30px]">
            Email Integrations
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Connect Gmail or Outlook to monitor travel emails and retrieve documents.
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

      <EmailConnectionSummary summary={summary} />

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
            {connections.data.map((connection) => (
              <EmailConnectionCard key={connection.id} connection={connection} controller={controller} />
            ))}
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

      <EmailConnectionDialogs controller={controller} />
    </div>
  );
}
