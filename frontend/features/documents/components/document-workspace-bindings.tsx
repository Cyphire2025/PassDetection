"use client";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

function DialogLoadingFallback() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div role="status" className="rounded-xl bg-white px-5 py-4 text-sm font-medium text-slate-700 shadow-xl">
        Loading secure dialog…
      </div>
    </div>
  );
}

export const AbortIncompleteUploadDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.AbortIncompleteUploadDialog),
  { loading: DialogLoadingFallback },
);
export const DocumentDeliveryPreviewDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.DocumentDeliveryPreviewDialog),
  { loading: DialogLoadingFallback },
);
export const RemoveAssignmentsDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.RemoveAssignmentsDialog),
  { loading: DialogLoadingFallback },
);
export const DocumentWorkspaceUploadStatus = dynamic(
  () => import("./document-workspace-upload-status").then((module) => module.DocumentWorkspaceUploadStatus),
  { loading: () => <Skeleton className="h-32 rounded-xl" /> },
);
export const DocumentManualReviewDialog = dynamic(
  () => import("./document-manual-review-dialog").then((module) => module.DocumentManualReviewDialog),
  { loading: DialogLoadingFallback },
);
export const DocumentFilenameConflictDialog = dynamic(
  () => import("./document-filename-conflict-dialog").then((module) => module.DocumentFilenameConflictDialog),
  { loading: DialogLoadingFallback },
);
export const DocumentWorkspaceReviewControls = dynamic(
  () => import("./document-workspace-review-controls").then((module) => module.DocumentWorkspaceReviewControls),
  { loading: () => <Skeleton className="h-40 rounded-xl" /> },
);
export const DocumentWorkspaceReviewRows = dynamic(
  () => import("./document-workspace-review-rows").then((module) => module.DocumentWorkspaceReviewRows),
  {
    loading: () => (
      <tbody>
        <tr>
          <td colSpan={8} className="px-5 py-10 text-center text-sm text-slate-500" role="status">
            Loading passenger documents…
          </td>
        </tr>
      </tbody>
    ),
  },
);
export const FlightTicketLaneNavigation = dynamic(
  () => import("./flight-ticket-lane-navigation").then((module) => module.FlightTicketLaneNavigation),
  { loading: () => <Skeleton className="h-24 rounded-xl" /> },
);
