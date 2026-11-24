"use client";

import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  FolderKanban,
  FolderOpen,
  Link2,
  UsersRound,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import type { PassportListModel } from "./use-passport-list";

type Props = Pick<
  PassportListModel,
  | "data"
  | "summary"
  | "isLoading"
  | "error"
  | "isFetching"
  | "refetch"
>;


export function PassportListOverview({ data, summary, isLoading, error, isFetching, refetch }: Props) {
  return (
    <>
      <WorkspacePageHeader
        title="All Groups"
        description="Review passport submissions and confirm passenger records by group."
        icon={FolderKanban}
        accent="sky"
        context={(
          <>
            <WorkspaceHeaderContext icon={FolderOpen}>
              {data ? `${data.length.toLocaleString()} groups` : isLoading ? "Loading groups" : "Groups unavailable"}
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={UsersRound}>
              {data ? `${summary.passports.toLocaleString()} passport records` : isLoading ? "Loading passport records" : "Passport records unavailable"}
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.uploadLinks}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold text-[#123f73] shadow-sm transition hover:bg-sky-50 active:bg-sky-100"
          >
            Manage Group Links
            <Link2 className="h-4 w-4" aria-hidden="true" />
          </IntentPrefetchLink>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          <p>{data
            ? "All Groups could not be refreshed. Previously loaded groups remain visible with your current filters and selection."
            : "All Groups could not be loaded. Group counts and workspaces are unavailable until loading succeeds."}</p>
          <Button type="button" variant="secondary" size="sm" className="mt-3" disabled={isFetching} onClick={() => void refetch()}>
            Retry
          </Button>
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="All Groups readiness summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Active portfolio"
              value={data ? data.length.toLocaleString() : "—"}
              helper={data ? "groups in scope" : "Unavailable"}
              icon={FolderKanban}
            />
            <WorkspaceSummaryItem
              label="Passport records"
              value={data ? summary.passports.toLocaleString() : "—"}
              helper={data ? "submitted" : "Unavailable"}
              icon={FileText}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Needs review"
              value={data ? summary.review.toLocaleString() : "—"}
              helper={data ? "records" : "Unavailable"}
              icon={AlertTriangle}
              tone={!data ? "default" : summary.review > 0 ? "attention" : "success"}
            />
            <WorkspaceSummaryItem
              label="Fully confirmed"
              value={data ? summary.confirmedGroups.toLocaleString() : "—"}
              helper={data ? "groups" : "Unavailable"}
              icon={CheckCircle2}
              tone={data ? "success" : "default"}
            />
          </>
        )}
      </WorkspaceSummaryStrip>
    </>
  );
}
