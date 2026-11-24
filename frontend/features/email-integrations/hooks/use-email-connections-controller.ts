"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
} from "./use-email-integrations";
import {
  cleanEmailOAuthCallbackUrl,
  isSafeOAuthAuthorizationUrl,
  readEmailOAuthCallback,
} from "../utils/email-integrations";

type Notice = {
  tone: "success" | "error" | "warning" | "info";
  message: string;
};

type AiSettingsTarget = {
  connection: EmailConnection;
  enabled: boolean;
};

export function useEmailConnectionsController() {
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

  const actionPending = useRef(false);

  function beginAction() {
    if (actionPending.current || anyConnectionMutation) return false;
    actionPending.current = true;
    return true;
  }

  function finishAction() {
    actionPending.current = false;
    setActiveConnectionId(null);
  }

  function startAuthorization(
    provider: "gmail" | "outlook",
    connectionId?: string,
  ) {
    if (!beginAction()) return;
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
          finishAction();
          return;
        }
        finishAction();
        window.location.assign(authorizationUrl);
      },
      onError: () => {
        setNotice({
          tone: "error",
          message: `${provider === "outlook" ? "Microsoft Outlook" : "Gmail"} authorization could not be started. Please try again.`,
        });
        finishAction();
      },
    });
  }

  function runConnectionAction(
    action: "sync" | "pause" | "resume",
    connectionId: string,
  ) {
    if (!beginAction()) return;
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
        finishAction();
      },
      onError: () => {
        setNotice({
          tone: "error",
          message: `The connection could not be ${action === "sync" ? "synchronized" : action === "pause" ? "paused" : "resumed"}. Please try again.`,
        });
        finishAction();
      },
    });
  }

  function openAiSettings(connection: EmailConnection, enabled: boolean) {
    if (actionPending.current || anyConnectionMutation) return;
    setNotice(null);
    updateAiSettings.reset();
    setAiSettingsTarget({ connection, enabled });
  }

  function closeAiSettings() {
    if (actionPending.current || updateAiSettings.isPending) return;
    setAiSettingsTarget(null);
    updateAiSettings.reset();
  }

  function confirmAiSettings() {
    if (!aiSettingsTarget || !beginAction()) return;
    const { connection, enabled } = aiSettingsTarget;
    setActiveConnectionId(connection.id);
    updateAiSettings.mutate(
      { connectionId: connection.id, enabled },
      {
        onSuccess: (response) => {
          finishAction();
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
          finishAction();
        },
      },
    );
  }

  function openRemoval(connection: EmailConnection) {
    if (actionPending.current || anyConnectionMutation) return;
    setNotice(null);
    removeConnection.reset();
    setRemovalConfirmation("");
    setRemoveTarget(connection);
  }

  function closeRemoval() {
    if (actionPending.current || removeConnection.isPending) return;
    setRemoveTarget(null);
    setRemovalConfirmation("");
    removeConnection.reset();
  }

  function confirmRemoval() {
    if (!removeTarget || !removalEmailMatches || !beginAction()) return;
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
          finishAction();
          setNotice({
            tone: response.storage_cleanup_pending ? "warning" : "success",
            message: response.storage_cleanup_pending
              ? "The account and visible integration data were removed. Final cleanup of unreferenced stored files will complete automatically."
              : response.message,
          });
        },
        onError: () => {
          finishAction();
        },
      },
    );
  }

  const removalEmailMatches =
    removeTarget !== null &&
    removalConfirmation.trim().toLowerCase() ===
    removeTarget.email_address.trim().toLowerCase();

  return {
    role, status, connections, summary, authorize, sync, pause, resume,
    removeConnection, updateAiSettings, notice, removeTarget,
    removalConfirmation, setRemovalConfirmation, aiSettingsTarget,
    activeConnectionId, gmailProvider, outlookProvider, canConnectGmail,
    canConnectOutlook, anyConnectionMutation, removalEmailMatches,
    startAuthorization, runConnectionAction, openAiSettings, closeAiSettings,
    confirmAiSettings, openRemoval, closeRemoval, confirmRemoval,
  };
}

export type EmailConnectionsController = ReturnType<typeof useEmailConnectionsController>;
