"use client";

import {
  Building2,
  Mail,
  Search,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
} from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  useEmailAiRolloutTargets,
  useUpdateEmailAiRolloutPolicy,
} from "../hooks/use-email-integrations";
import type {
  EmailAiRolloutScope,
  EmailAiRolloutTarget,
} from "../types";
import {
  Definition,
  EmailDialog,
  EmailNotice,
  EmailQueryError,
} from "./email-integrations-ui";

const ROLLOUT_SCOPES: ReadonlyArray<{
  value: EmailAiRolloutScope;
  label: string;
  singular: string;
  description: string;
  icon: LucideIcon;
}> = [
  {
    value: "agency",
    label: "Agencies",
    singular: "agency",
    description: "Pause or allow an entire agency",
    icon: Building2,
  },
  {
    value: "user",
    label: "Users",
    singular: "user",
    description: "Control one mailbox owner",
    icon: UserRound,
  },
  {
    value: "connection",
    label: "My mailboxes",
    singular: "mailbox",
    description: "Control one of your connected mailboxes",
    icon: Mail,
  },
];

type RolloutNotice = {
  tone: "success" | "error" | "warning" | "info";
  message: string;
};

type RolloutDecision = {
  target: EmailAiRolloutTarget;
  enabled: boolean;
};

export function EmailAiRolloutControl() {
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

  if (!isSuperAdmin) return null;

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

  return (
    <section aria-labelledby="email-ai-rollout-heading">
      <Card className="border-indigo-200">
        <CardHeader className="p-5 pb-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-lg bg-indigo-50 p-2 text-indigo-700">
                  <ShieldCheck className="h-5 w-5" aria-hidden="true" />
                </span>
                <CardTitle id="email-ai-rollout-heading">
                  AI rollout controls
                </CardTitle>
                <Badge variant="outline">SuperAdmin only</Badge>
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                Choose where travel AI is available during rollout. A global
                or parent pause always wins, and each mailbox owner must still
                opt in before analysis can run.
              </p>
            </div>
            {targets.isFetching && !targets.isLoading && (
              <span role="status" className="text-xs text-slate-500">
                Refreshing controls…
              </span>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-5 p-5 pt-0">
          {targets.data && !targets.data.global_enabled && (
            <EmailNotice tone="warning">
              Travel AI is globally paused. Lower-level Allow choices can be
              saved, but nothing becomes active until the global service is
              enabled.
            </EmailNotice>
          )}
          {targets.data
            && targets.data.global_enabled
            && !targets.data.global_notifications_enabled && (
              <EmailNotice tone="info">
                Analysis can run, but AI bell notifications are globally
                paused.
              </EmailNotice>
            )}
          {notice && (
            <EmailNotice tone={notice.tone}>{notice.message}</EmailNotice>
          )}

          <div
            className="grid gap-2 sm:grid-cols-3"
            aria-label="AI rollout scope"
          >
            {ROLLOUT_SCOPES.map((scope) => {
              const Icon = scope.icon;
              const isActive = scope.value === scopeType;
              return (
                <button
                  key={scope.value}
                  type="button"
                  aria-pressed={isActive}
                  className={`rounded-xl border p-3 text-left transition-colors ${
                    isActive
                      ? "border-indigo-300 bg-indigo-50 ring-1 ring-indigo-200"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  }`}
                  onClick={() => selectScope(scope.value)}
                >
                  <span className="flex items-center gap-2">
                    <Icon
                      className={`h-4 w-4 ${
                        isActive ? "text-indigo-700" : "text-slate-500"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="text-sm font-semibold text-slate-900">
                      {scope.label}
                    </span>
                  </span>
                  <span className="mt-1 block text-xs text-slate-500">
                    {scope.description}
                  </span>
                </button>
              );
            })}
          </div>

          <form
            className="flex flex-col gap-2 sm:flex-row sm:items-end"
            onSubmit={applySearch}
          >
            <div className="min-w-0 flex-1">
              <Input
                label={`Find ${activeScope.label.toLowerCase()}`}
                value={searchInput}
                maxLength={120}
                placeholder={`Search ${activeScope.label.toLowerCase()}`}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button
                type="submit"
                variant="secondary"
                leftIcon={<Search className="h-4 w-4" aria-hidden="true" />}
              >
                Search
              </Button>
              {search && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setSearchInput("");
                    setSearch("");
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </form>

          {targets.isLoading ? (
            <div aria-label="Loading AI rollout controls" className="space-y-3">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-32 rounded-xl" />
              ))}
            </div>
          ) : targets.isError ? (
            <EmailQueryError
              title="AI rollout controls could not be loaded."
              onRetry={() => void targets.refetch()}
            />
          ) : targets.data?.items.length ? (
            <ul className="space-y-3">
              {targets.data.items.map((target) => {
                const nextEnabled = nextDirectEnabled(target);
                const isUpdating =
                  updatePolicy.isPending
                  && updatePolicy.variables?.target_id === target.target_id;
                return (
                  <li
                    key={`${target.scope_type}-${target.target_id}`}
                    className="rounded-xl border border-slate-200 bg-white p-4"
                  >
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 flex-1">
                        <h3 className="break-words font-semibold text-slate-950">
                          {target.label}
                        </h3>
                        {target.detail && (
                          <p className="mt-1 break-words text-sm text-slate-600">
                            {target.detail}
                          </p>
                        )}
                        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                          <Definition term="Rule at this level">
                            <DirectRuleBadge
                              directEnabled={target.direct_enabled}
                            />
                          </Definition>
                          <Definition term="Effective state">
                            <Badge
                              variant={
                                target.effective_enabled
                                  ? "success"
                                  : "warning"
                              }
                              dot
                            >
                              {target.effective_enabled
                                ? "Rollout allowed"
                                : "Rollout paused"}
                            </Badge>
                          </Definition>
                        </dl>
                        <p className="mt-3 text-xs leading-5 text-slate-500">
                          {rolloutExplanation(target)}
                        </p>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant={nextEnabled ? "primary" : "danger"}
                        className="shrink-0"
                        isLoading={isUpdating}
                        disabled={updatePolicy.isPending}
                        onClick={() => openDecision(target, nextEnabled)}
                      >
                        {nextEnabled ? "Allow" : "Pause"}
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center">
              <h3 className="text-sm font-semibold text-slate-900">
                No matching {activeScope.label.toLowerCase()}
              </h3>
              <p className="mt-1 text-sm text-slate-600">
                Try a different search or choose another scope.
              </p>
            </div>
          )}

          {targets.data?.truncated && (
            <EmailNotice tone="warning">
              Only the first matching results are shown. Narrow the search to
              find a specific {activeScope.singular}.
            </EmailNotice>
          )}

          <p className="rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
            These controls govern rollout availability only. A global, agency,
            or user pause can keep a lower scope paused, and mailbox owner
            opt-in is still required. No setting here sends email or grants
            mailbox write access. My mailboxes lists only accounts you
            connected yourself.
          </p>
        </CardContent>
      </Card>

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
    </section>
  );
}

function DirectRuleBadge({
  directEnabled,
}: {
  directEnabled: boolean | null;
}) {
  if (directEnabled === null) {
    return <Badge variant="outline">Inherited</Badge>;
  }
  return (
    <Badge variant={directEnabled ? "success" : "warning"} dot>
      {directEnabled ? "Allowed here" : "Paused here"}
    </Badge>
  );
}

function nextDirectEnabled(target: EmailAiRolloutTarget) {
  if (target.direct_enabled !== null) return !target.direct_enabled;
  return !target.effective_enabled;
}

function rolloutExplanation(target: EmailAiRolloutTarget) {
  if (target.direct_enabled === false) {
    return "Paused directly at this level.";
  }
  if (target.direct_enabled === true && !target.effective_enabled) {
    return "Allowed here, but a global or parent pause still applies.";
  }
  if (target.direct_enabled === true) {
    return "Allowed here and not blocked by a parent setting.";
  }
  return target.effective_enabled
    ? "Inherited from the current parent rollout settings."
    : "Inherited, with a global or parent pause currently applying.";
}

function scopeSingular(scopeType: EmailAiRolloutScope) {
  return (
    ROLLOUT_SCOPES.find((scope) => scope.value === scopeType)?.singular
    ?? "rollout scope"
  );
}

function readRolloutError(error: unknown) {
  if (isRolloutConflict(error)) {
    return "This rollout control changed elsewhere. Close this window, review the refreshed state, and try again.";
  }
  if (
    typeof error === "object"
    && error !== null
    && "message" in error
    && typeof error.message === "string"
  ) {
    return error.message.slice(0, 300);
  }
  return "The rollout control could not be saved. Refresh and try again.";
}

function isRolloutConflict(error: unknown) {
  return (
    typeof error === "object"
    && error !== null
    && "code" in error
    && error.code === "HTTP_409"
  );
}
