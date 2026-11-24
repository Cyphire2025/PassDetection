"use client";

import { Button, Card, CardContent } from "@/components/ui";
import { Inbox, Mail } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ROUTES } from "@/constants/routes";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useEmailOperationalInbox } from "../hooks/use-email-integrations";
import type { EmailOperationalInboxView } from "../types";
import { EmailCardSkeletons, EmailNotice, EmailQueryError } from "./email-integrations-ui";
import { OperationalInboxCard } from "./operational-inbox-card";
import { INBOX_VIEWS } from "./operational-inbox-views";

export function EmailOperationalInboxPage() {
  const user = useAuthStore(selectUser);
  const [view, setView] =
    useState<EmailOperationalInboxView>("needs_attention");
  const inbox = useEmailOperationalInbox(user?.id, view);
  const items = useMemo(
    () => inbox.data?.pages.flatMap((page) => page.items) ?? [],
    [inbox.data],
  );
  const counts = inbox.data?.pages[0]?.counts;
  const activeView = INBOX_VIEWS.find((option) => option.value === view);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              AI-assisted travel operations
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-[30px]">
              Operations Inbox
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              Review updates, decisions, and drafts from your connected inboxes.
            </p>
          </div>
          <Link
            href={ROUTES.dashboard.emailIntegrations}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <Mail className="h-4 w-4" aria-hidden="true" />
            Connected accounts
          </Link>
        </div>
      </div>

      <EmailNotice tone="info">
        Prepared drafts can be reviewed and edited here, but sending remains
        manual. The platform cannot send, edit, or delete mail in connected
        Gmail or Outlook accounts.
      </EmailNotice>

      <div
        className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3"
        aria-label="Operations inbox views"
      >
        {INBOX_VIEWS.map((option) => {
          const Icon = option.icon;
          const isActive = option.value === view;
          const count = counts?.[option.value];
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={isActive}
              className={`rounded-xl border p-4 text-left transition-colors ${isActive
                ? "border-blue-300 bg-blue-50 ring-1 ring-blue-200"
                : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                }`}
              onClick={() => setView(option.value)}
            >
              <span className="flex items-center justify-between gap-3">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-lg ${isActive
                    ? "bg-blue-600 text-white"
                    : "bg-slate-100 text-slate-600"
                    }`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                {typeof count === "number" && (
                  <span className="text-lg font-bold text-slate-950">
                    {count.toLocaleString()}
                  </span>
                )}
              </span>
              <span className="mt-3 block text-sm font-semibold text-slate-900">
                {option.label}
              </span>
              <span className="mt-1 block text-xs leading-5 text-slate-500">
                {option.description}
              </span>
            </button>
          );
        })}
      </div>

      <section aria-labelledby="operations-inbox-results-heading">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2
              id="operations-inbox-results-heading"
              className="text-base font-semibold text-slate-900"
            >
              {activeView?.label ?? "Operational email activity"}
            </h2>
            <p className="mt-0.5 text-sm text-slate-500">
              {activeView?.description}
            </p>
          </div>
          {inbox.isFetching && !inbox.isLoading && (
            <span role="status" className="text-xs text-slate-500">
              Refreshing…
            </span>
          )}
        </div>

        {inbox.isLoading ? (
          <EmailCardSkeletons />
        ) : inbox.isError ? (
          <EmailQueryError
            title="The operations inbox could not be loaded."
            onRetry={() => void inbox.refetch()}
          />
        ) : items.length > 0 ? (
          <ol className="space-y-4">
            {items.map((item) => (
              <OperationalInboxCard key={item.analysis_id} item={item} />
            ))}
          </ol>
        ) : (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center px-6 py-12 text-center">
              <span className="rounded-full bg-slate-100 p-3 text-slate-600">
                <Inbox className="h-6 w-6" aria-hidden="true" />
              </span>
              <h3 className="mt-4 font-semibold text-slate-900">
                Nothing in {activeView?.label.toLowerCase() ?? "this view"}
              </h3>
              <p className="mt-1 max-w-lg text-sm text-slate-600">
                Updates will appear after your connected inbox synchronizes and email analysis finishes.
              </p>
            </CardContent>
          </Card>
        )}

        {inbox.isBrowsingHistory && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void inbox.returnToLatest()}
          >
            Return to latest
          </Button>
        )}
        {inbox.historyError && (
          <p role="alert" className="px-4 py-2 text-sm text-red-700">
            Older items could not be loaded. Try loading more again.
          </p>
        )}
        {inbox.hasNextPage && (
          <div className="mt-4 flex justify-center">
            <Button
              type="button"
              variant="secondary"
              isLoading={inbox.isFetchingNextPage}
              onClick={() => void inbox.fetchNextPage()}
            >
              Load older items
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

