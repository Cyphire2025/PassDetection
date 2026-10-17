import { WorkspaceSummaryItem, WorkspaceSummaryStrip } from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle, CheckCircle2, UsersRound, X } from "lucide-react";
import type { PassportGroupController } from "./use-passport-group-controller";

export function PassportGroupReadiness({ isLoading, groupDetails, submissionsView }: Pick<PassportGroupController, "isLoading" | "groupDetails" | "submissionsView">) {
  return <WorkspaceSummaryStrip label="Group passport readiness">
    {isLoading && !groupDetails ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />) : <>
      <WorkspaceSummaryItem label="Submitted" value={(submissionsView?.group_total ?? groupDetails?.total_passports ?? 0).toLocaleString()} helper="passengers" icon={UsersRound} tone="info" />
      <WorkspaceSummaryItem label="Needs review" value={(groupDetails?.pending_review_count ?? 0).toLocaleString()} helper="records" icon={AlertTriangle} tone={(groupDetails?.pending_review_count ?? 0) > 0 ? "attention" : "success"} />
      <WorkspaceSummaryItem label="Confirmed" value={(groupDetails?.confirmed_count ?? 0).toLocaleString()} helper="ready" icon={CheckCircle2} tone="success" />
      <WorkspaceSummaryItem label="Failed" value={(groupDetails?.failed_count ?? 0).toLocaleString()} helper="need recovery" icon={X} tone={(groupDetails?.failed_count ?? 0) > 0 ? "attention" : "default"} />
    </>}
  </WorkspaceSummaryStrip>;
}
