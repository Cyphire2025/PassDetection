"use client";

import Link from "next/link";
import { ArrowLeft, Cloud, FileText, Megaphone, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Badge, Card, CardContent, Skeleton, buttonVariants } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import {
  useGcAppGroupContent,
  useGcAppGroupControl,
  useGcAppGroupMutations,
} from "../hooks/use-gc-app-admin";
import type { AnnouncementInput, GcAppControlPatch } from "../types";
import { formatGcDateTime } from "../utils";
import { AnnouncementsPanel } from "./announcements-panel";
import { CommonDocumentsPanel } from "./common-documents-panel";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcAlert, GcLoadingRows } from "./gc-app-feedback";
import { GroupAccessPanel } from "./group-access-panel";

type WorkspaceTab = "access" | "documents" | "announcements";

const WORKSPACE_TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "access", label: "Access & status" },
  { value: "documents", label: "Common documents" },
  { value: "announcements", label: "Announcements" },
];

export function AppControlGroupWorkspace({ groupId }: { groupId: string }) {
  const { agencyId } = useGcAppAgencyScope();
  const [tab, setTab] = useState<WorkspaceTab>("access");
  const control = useGcAppGroupControl(agencyId, groupId);
  const content = useGcAppGroupContent(agencyId, groupId, tab !== "access");
  const actions = useGcAppGroupMutations(agencyId, groupId, control.data?.revision);

  if (control.isLoading) return <Card><GcLoadingRows count={4} /></Card>;
  if (control.isError || !control.data) {
    return <GcAlert message="This GC App group control could not be loaded. It may have been removed or your permission may have changed." />;
  }

  const updateControl = async (patch: GcAppControlPatch) => {
    await actions.updateControl.mutateAsync({ control: control.data, patch });
  };
  const setMyPhotosEnabled = async (enabled: boolean) => {
    await actions.setMyPhotosEnabled.mutateAsync({ control: control.data, enabled });
  };
  const revoke = async () => {
    await actions.revoke.mutateAsync(groupId);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title={control.data.name}
        description={`${control.data.destination ?? "Destination not set"} · GC App publishing workspace`}
        actions={(
          <Link href={ROUTES.dashboard.gcAppAppControls as never} className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to App Controls
          </Link>
        )}
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryMetric icon={<ShieldCheck className="h-4 w-4" />} label="Lifecycle" value={capitalize(control.data.lifecycle)} />
        <SummaryMetric icon={<Cloud className="h-4 w-4" />} label="Active users" value={String(control.data.active_mobile_users)} />
        <SummaryMetric icon={<Cloud className="h-4 w-4" />} label="Synced devices" value={String(control.data.synced_device_count)} />
        <SummaryMetric icon={<FileText className="h-4 w-4" />} label="Documents" value={`v${control.data.versions.common_document_version}`} />
        <SummaryMetric icon={<Megaphone className="h-4 w-4" />} label="Announcements" value={`v${control.data.versions.announcement_version}`} />
      </div>

      <Card>
        <CardContent className="flex flex-col gap-2 p-4 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between">
          <span>Last successful app synchronization: <strong className="text-slate-800">{control.data.last_successful_sync_at ? formatGcDateTime(control.data.last_successful_sync_at) : "Never"}</strong></span>
          {control.data.access_revoked_at && <Badge variant="destructive">Revoked {formatGcDateTime(control.data.access_revoked_at)}</Badge>}
        </CardContent>
      </Card>

      <div className="overflow-x-auto border-b border-slate-200">
        <div className="flex min-w-max gap-2" role="tablist" aria-label={`${control.data.name} App Controls`}>
          {WORKSPACE_TABS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={tab === item.value}
              onClick={() => setTab(item.value)}
              className={`min-h-11 border-b-2 px-4 text-sm font-medium transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
                tab === item.value ? "border-blue-600 text-blue-700" : "border-transparent text-slate-600 hover:text-slate-900"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "access" && (
        <div role="tabpanel">
          <GroupAccessPanel
            key={control.data.revision}
            control={control.data}
            isUpdating={actions.updateControl.isPending || actions.setMyPhotosEnabled.isPending || actions.revoke.isPending}
            onUpdate={updateControl}
            onSetMyPhotosEnabled={setMyPhotosEnabled}
            onRevoke={revoke}
          />
        </div>
      )}

      {(tab === "documents" || tab === "announcements") && content.isLoading && (
        <Card><CardContent className="p-5"><Skeleton className="h-72 w-full" /></CardContent></Card>
      )}
      {(tab === "documents" || tab === "announcements") && content.isError && (
        <GcAlert message="Published content and drafts could not be loaded. No content was changed." />
      )}

      {tab === "documents" && content.data && (
        <div role="tabpanel">
          <CommonDocumentsPanel
            documents={content.data.common_documents}
            isUploading={actions.uploadDocument.isPending}
            isUpdating={actions.setDocumentPublished.isPending || actions.reorderDocuments.isPending || actions.deleteDocument.isPending}
            previewingDocumentId={actions.previewDocument.isPending ? actions.previewDocument.variables : null}
            onUpload={async (upload) => { await actions.uploadDocument.mutateAsync(upload); }}
            onPreview={async (documentId) => actions.previewDocument.mutateAsync(documentId)}
            onSetPublished={async (documentId, published) => { await actions.setDocumentPublished.mutateAsync({ documentId, published }); }}
            onReorder={async (orderedDocumentIds) => { await actions.reorderDocuments.mutateAsync(orderedDocumentIds); }}
            onDelete={async (documentId) => { await actions.deleteDocument.mutateAsync(documentId); }}
          />
        </div>
      )}

      {tab === "announcements" && content.data && (
        <div role="tabpanel">
          <AnnouncementsPanel
            announcements={content.data.announcements}
            isCreating={actions.createAnnouncement.isPending}
            isUpdating={actions.updateAnnouncement.isPending || actions.setAnnouncementPublished.isPending || actions.deleteAnnouncement.isPending}
            onCreate={async (body) => { await actions.createAnnouncement.mutateAsync(body); }}
            onUpdate={async (announcementId, body: AnnouncementInput) => { await actions.updateAnnouncement.mutateAsync({ announcementId, body }); }}
            onSetPublished={async (announcementId, published) => { await actions.setAnnouncementPublished.mutateAsync({ announcementId, published }); }}
            onDelete={async (announcementId) => { await actions.deleteAnnouncement.mutateAsync(announcementId); }}
          />
        </div>
      )}
    </div>
  );
}

function SummaryMetric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <Card><CardContent className="p-4"><div className="flex items-center gap-2 text-xs text-slate-500">{icon}{label}</div><p className="mt-2 text-lg font-semibold text-slate-900">{value}</p></CardContent></Card>
  );
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
