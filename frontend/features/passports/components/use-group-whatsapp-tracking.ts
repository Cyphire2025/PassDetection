"use client";

import { useEffect, useState } from "react";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";
import { useExportWhatsAppTracking } from "../hooks/use-passports";
import {
  useGroupWhatsAppLinks,
  useGroupWhatsAppMatches,
  useRejectUnidentifiedUpload,
  useRestoreRosterResolution,
} from "../hooks/use-upload-links";
import { type MatchFilter } from "./group-whatsapp-tracking-model";
export function useGroupWhatsAppTracking(groupId: string, readOnly: boolean, mode: "summary" | "tracking") {
  const [matchFilter, setMatchFilter] = useState<MatchFilter>("all");
  const [broadcastFilter, setBroadcastFilter] = useState("all");
  const [matchPage, setMatchPage] = useState(1);
  const [isManaging, setIsManaging] = useState(false);
  const [replacementRow, setReplacementRow] = (useState<GroupWhatsAppMatch | null>(null));
  const [rejectRow, setRejectRow] = useState<GroupWhatsAppMatch | null>(null);
  const [rejectRequestId, setRejectRequestId] = useState<string | null>(null);
  const [restoreRow, setRestoreRow] = useState<GroupWhatsAppMatch | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);
  const matchPageSize = 50;
  const { data: links, isLoading: linksLoading, error: linksError } = (useGroupWhatsAppLinks(groupId));
  const hasLinkedBroadcasts = (links?.broadcast_count ?? 0) > 0;
  const canManage = Boolean(links?.can_manage) && !readOnly;
  const rejectUpload = useRejectUnidentifiedUpload(groupId);
  const restoreResolution = useRestoreRosterResolution(groupId);
  const exportTracking = useExportWhatsAppTracking();
  const matchesQuery = useGroupWhatsAppMatches(groupId, {
    status: matchFilter,
    sort_by: "name",
    sort_order: "asc",
    page: matchPage,
    page_size: matchPageSize,
    ...(broadcastFilter === "all"
      ? {}
      : { broadcast_id: broadcastFilter }),
  }, mode === "tracking" && hasLinkedBroadcasts);
  const totalRecipientCount = matchesQuery.data?.counts.total_recipients
    ?? (broadcastFilter === "all" ? links?.recipient_count ?? 0 : null);
  const submittedRecipientCount = (matchesQuery.data?.counts.submitted_count ?? null);
  const submissionRate = submittedRecipientCount !== null
    && totalRecipientCount !== null
    && totalRecipientCount > 0
    ? Math.round((submittedRecipientCount / totalRecipientCount) * 100)
    : null;
  useEffect(() => {
    const totalPages = matchesQuery.data?.total_pages;
    if (!totalPages || matchPage <= totalPages)
      return;
    const timer = window.setTimeout(() => {
      setMatchPage(Math.max(1, totalPages));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [matchPage, matchesQuery.data?.total_pages]);
  useEffect(() => {
    if (broadcastFilter === "all"
      || links?.broadcasts.some((broadcast) => broadcast.id === broadcastFilter)) {
      return;
    }
    const timer = window.setTimeout(() => {
      setBroadcastFilter("all");
      setMatchPage(1);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [broadcastFilter, links?.broadcasts]);
  return {
    groupId,
    matchFilter,
    setMatchFilter,
    broadcastFilter,
    setBroadcastFilter,
    matchPage,
    setMatchPage,
    isManaging,
    setIsManaging,
    replacementRow,
    setReplacementRow,
    rejectRow,
    setRejectRow,
    rejectRequestId,
    setRejectRequestId,
    restoreRow,
    setRestoreRow,
    resolutionError,
    setResolutionError,
    matchPageSize,
    links,
    linksLoading,
    linksError,
    hasLinkedBroadcasts,
    canManage,
    rejectUpload,
    restoreResolution,
    exportTracking,
    matchesQuery,
    totalRecipientCount,
    submittedRecipientCount,
    submissionRate,
  };
}
export type GroupWhatsAppTrackingModel = ReturnType<typeof useGroupWhatsAppTracking>;
