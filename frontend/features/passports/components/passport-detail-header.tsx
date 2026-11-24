"use client";
import { Activity, ArrowLeft, ChevronLeft, ChevronRight, FileCheck2, Gauge, History, QrCode } from "lucide-react";
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
import { PASSPORT_STATUS_LABELS } from "@/constants";
import { ROUTES } from "@/constants/routes";
import { formatConfidence } from "@/lib/utils/format";
import { getPassportTextField } from "@/lib/utils/passport-fields";
import type { PassportSubmission } from "@/types/passport.types";
import { buildPassportGroupHref } from "../utils/passport-group-navigation";
import { formatQrStatus, toLabel } from "./passport-review-model";
import type { usePassportDetailNavigation } from "./use-passport-detail-navigation";

export function PassportDetailLoading() {
    return (
      <div className="flex flex-col gap-5" aria-label="Loading passenger passport workspace">
        <WorkspacePageHeader
          title="Passport Submission"
          description="Loading the passenger record, document images, extraction review, and workflow status."
          icon={FileCheck2}
          accent="sky"
        />
        <WorkspaceSummaryStrip label="Loading passport record summary">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))}
        </WorkspaceSummaryStrip>
        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <Skeleton className="h-[32rem] w-full rounded-xl" />
          <Skeleton className="h-[32rem] w-full rounded-xl" />
        </div>
      </div>
    );
  }

export function PassportDetailError() {
    return (
      <div className="flex flex-col gap-5">
        <WorkspacePageHeader
          title="Passport Submission"
          description="Review the passenger record, extracted fields, and current workflow status."
          icon={FileCheck2}
          accent="sky"
        />
        <WorkspaceErrorNotice>
          This passport submission could not be loaded. Return to the group and try opening it again.
        </WorkspaceErrorNotice>
      </div>
    );
  }

export function PassportDetailHeader({ data, navigation }: { data: PassportSubmission; navigation: ReturnType<typeof usePassportDetailNavigation> }) {
  const { activeNavigation, orderedSubmissionIds, navigationIndex, previousHref, nextHref } = navigation;
  const groupHref = activeNavigation
    ? buildPassportGroupHref(
      data.group_id,
      activeNavigation.viewState,
      activeNavigation.includeDeleted,
    )
    : ROUTES.dashboard.passportGroup(data.group_id);
  const passportNumber = getPassportTextField(
    data.confirmed_fields ?? data.extracted_fields,
    "passport_number",
  );
  const workflowStatus = PASSPORT_STATUS_LABELS[data.status] ?? toLabel(data.status);
  return <>
      <WorkspacePageHeader
        title={data.client_name}
        description="Review passport images, correct extracted details, and verify the passenger record."
        icon={FileCheck2}
        accent="sky"
        context={(
          <>
            <WorkspaceHeaderContext icon={Activity}>{workflowStatus}</WorkspaceHeaderContext>
            {passportNumber && (
              <WorkspaceHeaderContext icon={FileCheck2}>Passport {passportNumber}</WorkspaceHeaderContext>
            )}
            {activeNavigation && navigationIndex >= 0 && (
              <WorkspaceHeaderContext icon={History}>
                Passenger {navigationIndex + 1} of {orderedSubmissionIds.length}
              </WorkspaceHeaderContext>
            )}
          </>
        )}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
          {activeNavigation && navigationIndex >= 0 && (
            <div
              className="flex items-center gap-1 rounded-lg border border-white/20 bg-white/10 p-1"
              role="group"
              aria-label="Passport profile navigation"
            >
              {previousHref ? (
                <IntentPrefetchLink
                  href={previousHref}
                  aria-label="Previous passport"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-white transition hover:bg-white/15"
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                </IntentPrefetchLink>
              ) : (
                <Button
                  type="button"
                  size="icon"
                  disabled
                  aria-label="No previous passport"
                  className="h-8 w-8 bg-transparent text-slate-400 shadow-none"
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
              <span className="min-w-20 px-1 text-center text-xs font-medium text-slate-100">
                {navigationIndex + 1} of {orderedSubmissionIds.length}
              </span>
              {nextHref ? (
                <IntentPrefetchLink
                  href={nextHref}
                  aria-label="Next passport"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-white transition hover:bg-white/15"
                >
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </IntentPrefetchLink>
              ) : (
                <Button
                  type="button"
                  size="icon"
                  disabled
                  aria-label="No next passport"
                  className="h-8 w-8 bg-transparent text-slate-400 shadow-none"
                >
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
            </div>
          )}
          <IntentPrefetchLink
            href={groupHref}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to Group
          </IntentPrefetchLink>
        </div>
        )}
      />

      <WorkspaceSummaryStrip label="Passenger passport record summary">
        <WorkspaceSummaryItem
          label="Workflow"
          value={workflowStatus}
          helper="current status"
          icon={Activity}
          tone={data.status === "confirmed" ? "success" : data.status === "failed" ? "attention" : "info"}
        />
        <WorkspaceSummaryItem
          label="Confidence"
          value={formatConfidence(data.verification_confidence)}
          helper="verification"
          icon={Gauge}
        />
        <WorkspaceSummaryItem
          label="Extraction revision"
          value={data.extraction_revision.toLocaleString()}
          helper="current"
          icon={History}
        />
        <WorkspaceSummaryItem
          label="Attendance QR"
          value={formatQrStatus(data.qr_status?.status ?? "not_generated")}
          helper={data.qr_status?.token_version ? `version ${data.qr_status.token_version}` : "passenger access"}
          icon={QrCode}
          tone={data.qr_status?.status === "active" ? "success" : "default"}
        />
      </WorkspaceSummaryStrip>
  </>;
}
