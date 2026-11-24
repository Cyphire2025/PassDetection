"use client";

import { Search, ShieldCheck } from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Skeleton } from "@/components/ui";
import { useEmailRolloutController } from "../hooks/use-email-rollout-controller";
import { EmailNotice, EmailQueryError } from "./email-integrations-ui";
import { EmailRolloutTarget } from "./email-rollout-target";
import { EmailRolloutDecision } from "./email-rollout-decision";
import { ROLLOUT_SCOPES } from "./email-rollout-model";

export function EmailAiRolloutControl() {
  const controller = useEmailRolloutController();
  const { isSuperAdmin, scopeType, searchInput, setSearchInput, search,
    setSearch, notice, targets, updatePolicy, activeScope,
    selectScope, applySearch, openDecision } = controller;
  if (!isSuperAdmin) return null;

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
                  className={`rounded-xl border p-3 text-left transition-colors ${isActive
                    ? "border-indigo-300 bg-indigo-50 ring-1 ring-indigo-200"
                    : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                    }`}
                  onClick={() => selectScope(scope.value)}
                >
                  <span className="flex items-center gap-2">
                    <Icon
                      className={`h-4 w-4 ${isActive ? "text-indigo-700" : "text-slate-500"
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
              {targets.data.items.map((target) => (
                <EmailRolloutTarget key={`${target.scope_type}-${target.target_id}`}
                  target={target} pending={updatePolicy.isPending}
                  isUpdating={updatePolicy.isPending && updatePolicy.variables?.target_id === target.target_id}
                  onDecision={openDecision} />
              ))}
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

      <EmailRolloutDecision controller={controller} />
    </section>
  );
}

