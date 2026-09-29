"use client";

import { ChevronRight, Link2, MessageCircle } from "lucide-react";
import Link from "next/link";
import { Button, buttonVariants, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import type { GroupWhatsAppLinksResponse } from "../api/upload-links.api";
import { broadcastMatchingSummary } from "./whatsapp-match-field-selector";

export function GroupWhatsAppSummary({ groupId, links, hasError, canManage, onManage }: {
  groupId: string;
  links: GroupWhatsAppLinksResponse | undefined;
  hasError: boolean;
  canManage: boolean;
  onManage: () => void;
}) {
  const hasLinkedBroadcasts = (links?.broadcast_count ?? 0) > 0;
  return (
    <Card className="h-full min-w-0">
      <CardContent className="flex h-full min-h-52 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
            <MessageCircle className="h-4 w-4" aria-hidden="true" />
          </span>
          <h2 className="text-sm font-semibold text-slate-900">WhatsApp broadcasts</h2>
        </div>
        <div className="min-w-0 flex-1">
          {hasError ? (
            <p role="alert" className="text-sm text-red-700">Linked WhatsApp broadcasts could not be loaded.</p>
          ) : !hasLinkedBroadcasts ? (
            <>
              <p className="text-sm font-medium text-slate-800">No WhatsApp broadcasts linked</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">Link a recipient list to track passport submissions.</p>
            </>
          ) : (
            <>
              <p className="truncate text-base font-semibold text-slate-900" title={links?.broadcasts[0]?.name}>
                {links?.broadcasts[0]?.name}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {links?.recipient_count.toLocaleString()} recipients · {links?.broadcast_count.toLocaleString()} linked {links?.broadcast_count === 1 ? "list" : "lists"}
              </p>
              <p className="mt-1 truncate text-xs text-slate-500" title={links?.broadcasts[0] ? broadcastMatchingSummary(links.broadcasts[0]) : undefined}>
                {links?.broadcast_count === 1 && links.broadcasts[0]
                  ? broadcastMatchingSummary(links.broadcasts[0])
                  : "View tracking to compare all linked lists."}
              </p>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
          {canManage && (
            <Button type="button" variant="secondary" size="sm" onClick={onManage}>
              <Link2 className="h-4 w-4" aria-hidden="true" />
              {hasLinkedBroadcasts ? "Manage broadcasts" : "Link broadcasts"}
            </Button>
          )}
          {hasLinkedBroadcasts && (
            <Link href={ROUTES.dashboard.passportGroupWhatsAppTracking(groupId)} className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "ml-auto shrink-0")}>
              View tracking
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
