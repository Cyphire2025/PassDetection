"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, buttonVariants } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import {
  useGcAppGroupContent,
  useGcAppGroupControl,
  useGcAppGroupMutations,
  useGcAppGroupAudit,
  useGcAppAnnouncements,
} from "../hooks/use-gc-app-admin";
import type { AnnouncementInput, GcAppControlPatch } from "../types";
import { formatGcDateTime } from "../utils";
import { describeAppAvailability } from "../availability";
import { AnnouncementsPanel } from "./announcements-panel";
import { CommonDocumentsPanel } from "./common-documents-panel";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { GroupAccessPanel } from "./group-access-panel";
import { GroupAppOverview, type GroupWorkspaceTab } from "./group-app-overview";
import { AuditTimeline } from "./audit-timeline";

const WORKSPACE_TABS: { value: GroupWorkspaceTab; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "access", label: "Access & features" },
  { value: "documents", label: "Documents" },
  { value: "announcements", label: "Announcements" },
  { value: "history", label: "History" },
];

export function AppControlGroupWorkspace({ groupId }: { groupId: string }) {
  const { agencyId } = useGcAppAgencyScope();
  const [tab, setTab] = useState<GroupWorkspaceTab>("overview");
  const [announcementPage, setAnnouncementPage] = useState(1);
  const [historyPage, setHistoryPage] = useState(1);
  const control = useGcAppGroupControl(agencyId, groupId);
  const content = useGcAppGroupContent(agencyId, groupId, tab === "documents" && !control.data?.gc_removed_at);
  const announcements = useGcAppAnnouncements(agencyId, groupId, announcementPage, 25, tab === "announcements" && !control.data?.gc_removed_at);
  const history = useGcAppGroupAudit(agencyId, groupId, historyPage, 25, tab === "history");
  const actions = useGcAppGroupMutations(agencyId, groupId, control.data?.revision);

  if (control.isLoading) return <Card><GcLoadingRows count={4} /></Card>;
  if (!control.data) {
    return <div className="space-y-3"><GcAlert message="This GC App trip could not be loaded. It may have been removed or your permission may have changed." /><Button type="button" onClick={() => void control.refetch()}>Retry</Button></div>;
  }
  if (control.data.gc_removed_at) {
    return <div className="space-y-4">
      <PageHeader title={control.data.name} description="Removed from GC App" />
      <GcAlert tone="info" message="This trip was removed from GC App. Its original group, travellers, documents and history are kept. To restore an eligible group, use Add group to GC App in App Controls." />
      <Link href={ROUTES.dashboard.gcAppAppControls as never} className={buttonVariants({ variant: "secondary" })}>Back to App Controls</Link>
      <Button type="button" variant="secondary" onClick={() => setTab("history")}>View history</Button>
      {tab === "history" && <Card>
        {history.isLoading ? <GcLoadingRows count={3} /> : history.isError ? <GcAlert message="History could not be loaded." /> : <AuditTimeline events={history.data?.items ?? []} />}
        {history.data && <GcPagination page={history.data.page} total={history.data.total} pageSize={history.data.page_size}
          hasNext={history.data.has_next} disabled={history.isFetching} onPageChange={setHistoryPage} />}
      </Card>}
    </div>;
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
  const availability = describeAppAvailability(control.data);
  const updating = control.isError || actions.updateControl.isPending || actions.setMyPhotosEnabled.isPending || actions.revoke.isPending;

  return (
    <div className="space-y-5">
      <PageHeader
        title={control.data.name}
        description={`${control.data.destination ?? "Destination not set"} · ${control.data.company?.name ?? "Company/client not assigned"}`}
        actions={(
          <Link href={ROUTES.dashboard.gcAppAppControls as never} className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to App Controls
          </Link>
        )}
      />

      {control.isError && <GcAlert message="Trip settings could not be refreshed. Your edits are kept, but changes are disabled until the current settings load successfully." />}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm text-slate-600">
          <div className="space-y-1"><Badge variant={availability.variant}>App: {availability.label}</Badge>
            <p className="text-xs">Availability checked {formatGcDateTime(control.data.app_availability_evaluated_at ?? null)}</p>
          </div>
          <div className="text-xs">{control.data.active_mobile_users} active users · {control.data.synced_device_count} synced devices<br />Last successful sync: {control.data.last_successful_sync_at ? formatGcDateTime(control.data.last_successful_sync_at) : "Never"}</div>
          <Button type="button" size="sm" variant="secondary" isLoading={control.isFetching} onClick={() => void control.refetch()}>Refresh trip status</Button>
        </CardContent>
      </Card>

      <div className="border-b border-slate-200">
        <div className="grid grid-cols-3 gap-1 sm:flex sm:gap-2" role="tablist" aria-label={`${control.data.name} App Controls`}>
          {WORKSPACE_TABS.map((item, index) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              id={`gc-trip-tab-${item.value}`}
              aria-controls={`gc-trip-panel-${item.value}`}
              aria-selected={tab === item.value}
              tabIndex={tab === item.value ? 0 : -1}
              onClick={() => setTab(item.value)}
              onKeyDown={(event) => {
                const nextIndex = event.key === "ArrowRight" ? (index + 1) % WORKSPACE_TABS.length
                  : event.key === "ArrowLeft" ? (index + WORKSPACE_TABS.length - 1) % WORKSPACE_TABS.length
                    : event.key === "Home" ? 0 : event.key === "End" ? WORKSPACE_TABS.length - 1 : null;
                if (nextIndex === null) return;
                event.preventDefault();
                const next = WORKSPACE_TABS[nextIndex]!;
                setTab(next.value);
                document.getElementById(`gc-trip-tab-${next.value}`)?.focus();
              }}
              className={`min-h-11 border-b-2 px-2 text-xs font-medium transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 sm:px-4 sm:text-sm ${
                tab === item.value ? "border-blue-600 text-blue-700" : "border-transparent text-slate-600 hover:text-slate-900"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "overview" && <div role="tabpanel" id="gc-trip-panel-overview" aria-labelledby="gc-trip-tab-overview"><GroupAppOverview control={control.data} onNavigate={setTab} /></div>}

        <div role="tabpanel" id="gc-trip-panel-access" aria-labelledby="gc-trip-tab-access" hidden={tab !== "access"}>
          <GroupAccessPanel
            key={groupId}
            control={control.data}
            isUpdating={updating}
            onUpdate={updateControl}
            onSetMyPhotosEnabled={setMyPhotosEnabled}
            onRevoke={revoke}
          />
        </div>
      {tab === "documents" && content.isLoading && (
        <Card><GcLoadingRows count={3} /></Card>
      )}
      {tab === "documents" && content.isError && (
        <div className="space-y-3"><GcAlert message="Documents could not be refreshed. Last loaded documents are shown when available; refresh before changing them." /><Button type="button" onClick={() => void content.refetch()}>Retry documents</Button></div>
      )}

      {content.data && (
        <div role="tabpanel" id="gc-trip-panel-documents" aria-labelledby="gc-trip-tab-documents" hidden={tab !== "documents"}>
          <CommonDocumentsPanel
            documents={content.data.common_documents}
            isUploading={actions.uploadDocument.isPending}
            disabled={control.isError || content.isError || control.data.lifecycle === "archived" || control.data.lifecycle === "deleted"}
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

      {tab === "announcements" && announcements.isLoading && <Card><GcLoadingRows count={3} /></Card>}
      {tab === "announcements" && announcements.isError && <div className="space-y-3"><GcAlert message="Announcements could not be refreshed. Your draft is kept; refresh before publishing changes." /><Button type="button" onClick={() => void announcements.refetch()}>Retry announcements</Button></div>}
      {announcements.data && (
        <div role="tabpanel" id="gc-trip-panel-announcements" aria-labelledby="gc-trip-tab-announcements" hidden={tab !== "announcements"} className="space-y-4">
          <AnnouncementsPanel
            announcements={announcements.data.items}
            total={announcements.data.total}
            disabled={control.isError || announcements.isError || control.data.lifecycle === "archived" || control.data.lifecycle === "deleted"}
            appAvailability={control.data.app_availability}
            isCreating={actions.createAnnouncement.isPending}
            isUpdating={actions.updateAnnouncement.isPending || actions.setAnnouncementPublished.isPending || actions.deleteAnnouncement.isPending}
            onCreate={async (body) => { await actions.createAnnouncement.mutateAsync(body); }}
            onUpdate={async (announcementId, body: AnnouncementInput) => { await actions.updateAnnouncement.mutateAsync({ announcementId, body }); }}
            onSetPublished={async (announcementId, published) => { await actions.setAnnouncementPublished.mutateAsync({ announcementId, published }); }}
            onDelete={async (announcementId) => { await actions.deleteAnnouncement.mutateAsync(announcementId); }}
          />
          <GcPagination page={announcements.data.page} total={announcements.data.total} pageSize={announcements.data.page_size} hasNext={announcements.data.has_next} disabled={announcements.isFetching || actions.createAnnouncement.isPending || actions.updateAnnouncement.isPending} onPageChange={setAnnouncementPage} />
        </div>
      )}
      {tab === "history" && <div role="tabpanel" id="gc-trip-panel-history" aria-labelledby="gc-trip-tab-history" className="space-y-4">
        {history.isLoading && <Card><GcLoadingRows count={3} /></Card>}
        {history.isError && <div className="space-y-3"><GcAlert message="Change history could not be refreshed." /><Button type="button" onClick={() => void history.refetch()}>Retry history</Button></div>}
        {history.data && <><AuditTimeline events={history.data.items} /><GcPagination page={history.data.page} total={history.data.total} pageSize={history.data.page_size} hasNext={history.data.has_next} disabled={history.isFetching} onPageChange={setHistoryPage} /></>}
        <details className="rounded-xl border border-slate-200 p-4 text-xs text-slate-500"><summary className="cursor-pointer font-medium">Synchronization versions</summary><p className="mt-2">These counters track app synchronization changes, not the number of documents or announcements.</p><p className="mt-2">Itinerary v{control.data.versions.itinerary_version} · Documents v{control.data.versions.common_document_version} · Announcements v{control.data.versions.announcement_version}</p></details>
      </div>}
    </div>
  );
}
