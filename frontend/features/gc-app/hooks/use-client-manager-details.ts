"use client";

import { useEffect, useRef, useState } from "react";
import {
  useClientManagerAudit,
  useClientManagerMutations,
  useClientManagerSessions,
} from "./use-gc-app-admin";
import type {
  ClientManagerDetailsProps,
  DetailTab,
  Confirmation,
} from "../components/client-manager-details.types";
import { gcAppErrorMessage } from "../utils";

export function useClientManagerDetails({ open, agencyId, manager, onClose, onUpdated }: ClientManagerDetailsProps) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [activationToken, setActivationToken] = useState<string | null>(null);
  const [activationCopied, setActivationCopied] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sessionsPage, setSessionsPage] = useState(1);
  const [auditPage, setAuditPage] = useState(1);
  const actionInFlight = useRef(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!open) return;
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [open]);
  const managerId = manager?.id ?? null;
  const sessions = useClientManagerSessions(
    agencyId,
    tab === "sessions" ? managerId : null,
    sessionsPage,
  );
  const audit = useClientManagerAudit(
    agencyId,
    tab === "audit" ? managerId : null,
    auditPage,
  );
  const actions = useClientManagerMutations(agencyId);
  const isPending = actions.setStatus.isPending
    || actions.resetPassword.isPending
    || actions.revokeSessions.isPending
    || actions.softDelete.isPending;

  const resetViewState = () => {
    setTab("overview");
    setConfirmation(null);
    setPasswordOpen(false);
    setActivationToken(null);
    setActivationCopied(false);
    setDeleteConfirmation("");
    setError(null);
    setSessionsPage(1);
    setAuditPage(1);
  };

  const closeDetails = () => {
    resetViewState();
    onClose();
  };

  if (!manager) return null;

  const runConfirmation = async () => {
    if (!confirmation || actionInFlight.current) return;
    actionInFlight.current = true;
    setError(null);
    try {
      if (confirmation === "suspend") {
        onUpdated(await actions.setStatus.mutateAsync({ managerId: manager.id, status: "suspended", revision: manager.revision }));
      } else if (confirmation === "reactivate") {
        onUpdated(await actions.setStatus.mutateAsync({ managerId: manager.id, status: "active", revision: manager.revision }));
      } else if (confirmation === "revoke") {
        await actions.revokeSessions.mutateAsync(manager.id);
        setSessionsPage(1);
      } else if (confirmation === "delete") {
        if (deleteConfirmation !== "DELETE") {
          setError("Type DELETE to confirm safe account removal.");
          return;
        }
        await actions.softDelete.mutateAsync(manager.id);
        closeDetails();
      }
      setConfirmation(null);
      setDeleteConfirmation("");
    } catch (actionError) {
      setError(gcAppErrorMessage(actionError, "The account security action could not be completed."));
    } finally {
      actionInFlight.current = false;
    }
  };

  const resetPassword = async () => {
    if (actionInFlight.current) return;
    actionInFlight.current = true;
    setError(null);
    try {
      const updated = await actions.resetPassword.mutateAsync(manager.id);
      if (!updated.activation_token) throw new Error("Activation link was not returned");
      onUpdated({ ...updated, activation_token: undefined, temporary_password: undefined });
      setActivationToken(updated.activation_token);
      setActivationCopied(false);
    } catch (actionError) {
      setError(gcAppErrorMessage(actionError, "The credential reset link could not be issued."));
    } finally {
      actionInFlight.current = false;
    }
  };

  return {
    manager, tab, setTab, confirmation, setConfirmation, passwordOpen, setPasswordOpen,
    activationToken, setActivationToken, activationCopied, setActivationCopied,
    deleteConfirmation, setDeleteConfirmation, error, setError, sessions, audit,
    setSessionsPage, setAuditPage, now, actions, isPending, resetViewState,
    closeDetails, runConfirmation, resetPassword,
  };
}
