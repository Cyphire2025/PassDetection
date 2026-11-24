"use client";

import { ArrowLeft, Link2, MessageCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import { selectHasHydrated, selectUserRole, useAuthStore } from "@/stores/auth.store";
import { broadcastMatchingSummary } from "./whatsapp-match-field-selector";
import { GroupWhatsAppTrackingGate } from "./group-whatsapp-tracking-gate";
import { ManageBroadcastsDialog } from "./group-whatsapp-dialogs";
import { GroupWhatsAppSummary } from "./group-whatsapp-summary";
import { useGroupWhatsAppTracking } from "./use-group-whatsapp-tracking";
import { GroupWhatsAppTrackingStats } from "./group-whatsapp-tracking-stats";
import { GroupWhatsAppComparisonPanel } from "./group-whatsapp-comparison-panel";
import { GroupWhatsAppResolutionDialogs } from "./group-whatsapp-resolution-dialogs";

interface GroupWhatsAppBroadcastPanelProps {
  groupId: string;
  readOnly?: boolean;
}

export function GroupWhatsAppBroadcastPanel({
  groupId,
  readOnly = false,
}: GroupWhatsAppBroadcastPanelProps) {
  return (
    <GroupWhatsAppBroadcastWorkspace
      groupId={groupId}
      readOnly={readOnly}
      mode="summary"
    />
  );
}

export function GroupWhatsAppBroadcastTrackingPage({
  groupId,
}: {
  groupId: string;
}) {
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const role = useAuthStore(selectUserRole);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);

  useEffect(() => {
    if (!hasHydrated || role === null || canAccessWhatsApp) return;
    router.replace(
      (role === "agency_coordinator"
        ? ROUTES.coordinator
        : ROUTES.dashboard.passports),
    );
  }, [canAccessWhatsApp, hasHydrated, role, router]);

  if (!hasHydrated || !canAccessWhatsApp) return null;

  return (
    <GroupWhatsAppTrackingGate groupId={groupId}>
    <div className="space-y-5">
      <WorkspacePageHeader
        title="WhatsApp Submission Tracking"
        description="Compare broadcast recipients with passport submissions and review unmatched records."
        icon={MessageCircle}
        accent="emerald"
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.passportGroup(groupId)}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to group
          </IntentPrefetchLink>
        )}
      />
      <GroupWhatsAppBroadcastWorkspace groupId={groupId} mode="tracking" />
    </div>
    </GroupWhatsAppTrackingGate>
  );
}

function GroupWhatsAppBroadcastWorkspace({
  groupId,
  readOnly = false,
  mode,
}: GroupWhatsAppBroadcastPanelProps & {
  mode: "summary" | "tracking";
}) {
  const tracking = useGroupWhatsAppTracking(groupId, readOnly, mode);

  const {
    isManaging,
    setIsManaging,
    links,
    linksLoading,
    linksError,
    hasLinkedBroadcasts,
    canManage,
  } = tracking;

  if (linksLoading) {
    return <Skeleton className="h-52 w-full rounded-xl" />;
  }

  if (mode === "summary") {
    return (
      <>
        <GroupWhatsAppSummary
          groupId={groupId}
          links={links}
          hasError={Boolean(linksError)}
          canManage={canManage}
          onManage={() => setIsManaging(true)}
        />

        {isManaging && (
          <ManageBroadcastsDialog
            groupId={groupId}
            initialBroadcasts={links?.broadcasts ?? []}
            onClose={() => setIsManaging(false)}
          />
        )}
      </>
    );
  }

  return (
    <>
      <Card>
        <CardContent className="space-y-5 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                <MessageCircle className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  WhatsApp broadcast tracking
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Each recipient is identified when any selected spreadsheet field
                  matches a submitted value. If a value is ambiguous, it stays in
                  Needs review instead of being guessed.
                </p>
              </div>
            </div>
            {canManage && (
              <Button
                type="button"
                variant={hasLinkedBroadcasts ? "secondary" : "primary"}
                size="sm"
                onClick={() => setIsManaging(true)}
              >
                <Link2 className="h-4 w-4" aria-hidden="true" />
                {hasLinkedBroadcasts ? "Manage broadcasts" : "Link broadcasts"}
              </Button>
            )}
          </div>

          {linksError ? (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Linked WhatsApp broadcasts could not be loaded.
            </div>
          ) : !hasLinkedBroadcasts ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center">
              <div className="font-medium text-slate-800">No WhatsApp broadcasts linked</div>
              <p className="mt-1 text-sm text-slate-500">
                Link one or more existing broadcasts to see who has or has not submitted.
              </p>
            </div>
          ) : (
            <>
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Linked broadcasts
                </div>
                <div className="flex flex-wrap gap-2">
                  {links?.broadcasts.map((broadcast) => (
                    <span
                      key={broadcast.id}
                      className="inline-flex max-w-full items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-900"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{broadcast.name}</span>
                        <span className="block truncate text-[11px] text-emerald-700">
                          {broadcastMatchingSummary(broadcast)}
                        </span>
                      </span>
                      <span className="text-xs text-emerald-700">
                        {broadcast.recipient_count.toLocaleString()}
                      </span>
                    </span>
                  ))}
                </div>
              </div>

              <GroupWhatsAppTrackingStats {...tracking} />

              <GroupWhatsAppComparisonPanel {...tracking} />
            </>
          )}
        </CardContent>
      </Card>

      <GroupWhatsAppResolutionDialogs {...tracking} />
    </>
  );
}
