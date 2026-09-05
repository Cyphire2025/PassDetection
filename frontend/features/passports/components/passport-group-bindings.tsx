import { Skeleton } from "@/components/ui";
import dynamic from "next/dynamic";

export const GroupWhatsAppBroadcastPanel = dynamic(
  () =>
    import("./group-whatsapp-broadcast-panel").then(
      (module) => module.GroupWhatsAppBroadcastPanel,
    ),
  { loading: () => <Skeleton className="h-56 w-full rounded-xl" /> },
);

export const GroupDocumentDeliveryPanel = dynamic(
  () =>
    import("./group-document-delivery-panel").then(
      (module) => module.GroupDocumentDeliveryPanel,
    ),
  { loading: () => <Skeleton className="h-44 w-full rounded-xl" /> },
);

export const PassportImageCropEditor = dynamic(
  () =>
    import("./passport-image-crop-editor").then(
      (module) => module.PassportImageCropEditor,
    ),
  { loading: () => null },
);

export const PassportExportDialog = dynamic(
  () =>
    import("./passport-export-dialog").then(
      (module) => module.PassportExportDialog,
    ),
  { loading: () => null },
);

export const PassportDocumentImportProgress = dynamic(
  () =>
    import("./passport-document-import-dialog").then(
      (module) => module.PassportDocumentImportProgress,
    ),
  {
    loading: () => (
      <PassportWorkflowLoadingOverlay label="Loading passport import progress" />
    ),
  },
);

export const PassportDocumentImportDialog = dynamic(
  () =>
    import("./passport-document-import-dialog").then(
      (module) => module.PassportDocumentImportDialog,
    ),
  {
    loading: () => (
      <PassportWorkflowLoadingOverlay label="Loading passport document review" />
    ),
  },
);

export const TripDetailsDialog = dynamic(
  () =>
    import("./passport-trip-details-dialog").then(
      (module) => module.TripDetailsDialog,
    ),
  {
    loading: () => (
      <PassportWorkflowLoadingOverlay label="Loading trip settings" />
    ),
  },
);

export const PassportRetentionControl = dynamic(
  () =>
    import("./passport-retention-control").then(
      (module) => module.PassportRetentionControl,
    ),
  { loading: () => <Skeleton className="h-48 w-full rounded-xl" /> },
);

export function PassportWorkflowLoadingOverlay({ label }: { label: string }) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4"
      role="status"
      aria-live="polite"
    >
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <p className="text-sm font-semibold text-slate-700">{label}</p>
        <Skeleton className="mt-4 h-3 w-full rounded-full" />
      </div>
    </div>
  );
}

export interface PassportGroupDetailProps {
  groupId: string;
}

export const MAX_BULK_SELECTION = 1500;

export const MAX_SELECTED_IMAGE_DOWNLOAD = 500;
