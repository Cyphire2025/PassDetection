"use client";

import { useState, type FormEvent } from "react";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useEmailAiRolloutTargets, useUpdateEmailAiRolloutPolicy } from "./use-email-integrations";
import type { EmailAiRolloutScope, EmailAiRolloutTarget } from "../types";
import { ROLLOUT_SCOPES, isRolloutConflict, type RolloutDecision, type RolloutNotice } from "../components/email-rollout-model";

export function useEmailRolloutController() {
  const user = useAuthStore(selectUser);
  const isSuperAdmin = user?.role === "super_admin";
  const [scopeType, setScopeType] =
    useState<EmailAiRolloutScope>("agency");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [decision, setDecision] = useState<RolloutDecision | null>(null);
  const [notice, setNotice] = useState<RolloutNotice | null>(null);
  const targets = useEmailAiRolloutTargets(
    user?.id,
    scopeType,
    search,
    isSuperAdmin,
  );
  const updatePolicy = useUpdateEmailAiRolloutPolicy(user?.id);
  const activeScope =
    ROLLOUT_SCOPES.find((scope) => scope.value === scopeType)
    ?? ROLLOUT_SCOPES[0];

  function selectScope(nextScope: EmailAiRolloutScope) {
    setScopeType(nextScope);
    setSearchInput("");
    setSearch("");
    setNotice(null);
    setDecision(null);
    updatePolicy.reset();
  }

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  function openDecision(
    target: EmailAiRolloutTarget,
    enabled: boolean,
  ) {
    setNotice(null);
    updatePolicy.reset();
    setDecision({ target, enabled });
  }

  function closeDecision() {
    if (updatePolicy.isPending) return;
    setDecision(null);
    updatePolicy.reset();
  }

  function saveDecision() {
    if (!decision) return;
    updatePolicy.mutate(
      {
        scope_type: decision.target.scope_type,
        target_id: decision.target.target_id,
        agency_id: decision.target.agency_id,
        enabled: decision.enabled,
        expected_updated_at: decision.target.updated_at,
      },
      {
        onSuccess: (updated) => {
          setDecision(null);
          setNotice({
            tone:
              updated.direct_enabled && !updated.effective_enabled
                ? "info"
                : "success",
            message: updated.direct_enabled
              ? updated.effective_enabled
                ? `${updated.label} is allowed by the rollout controls.`
                : `${updated.label} is allowed here, but a parent or global pause still applies.`
              : `${updated.label} is paused at this level.`,
          });
        },
        onError: (error) => {
          if (!isRolloutConflict(error)) return;
          setDecision(null);
          setNotice({
            tone: "warning",
            message:
              "This rollout control changed elsewhere. The latest settings are being refreshed; review the current state before trying again.",
          });
        },
      },
    );
  }

  return {
    isSuperAdmin, scopeType, searchInput, setSearchInput, search,
    setSearch, decision, notice, targets, updatePolicy, activeScope,
    selectScope, applySearch, openDecision, closeDecision, saveDecision
  };
}

export type EmailRolloutController = ReturnType<typeof useEmailRolloutController>;
