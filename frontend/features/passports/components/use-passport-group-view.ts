"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { PassportGroupSubmissionFilter, PassportGroupSubmissionSort } from "../api/passports.api";
import { useGroupSubmissionsView } from "../hooks/use-passports";
import {
  buildPassportDetailNavigationHref,
  buildPassportGroupHref,
  createPassportNavigationToken,
  parsePassportGroupViewState,
  storePassportNavigationContext,
  type PassportDetailNavigationState,
  type PassportGroupViewState,
} from "../utils/passport-group-navigation";

export function usePassportGroupView(groupId: string, currentUserId: string | null) {
  const searchParams = useSearchParams();
  const includeDeleted = searchParams.get("old_data") === "1";
  const [search, setSearch] = useState(() => parsePassportGroupViewState(searchParams).search);
  const [debouncedSearch, setDebouncedSearch] = useState(() => parsePassportGroupViewState(searchParams).search);
  const [submissionFilter, setSubmissionFilter] =
    useState<PassportGroupSubmissionFilter>(() => parsePassportGroupViewState(searchParams).submissionFilter);
  const [sortBy, setSortBy] =
    useState<PassportGroupSubmissionSort>(() => parsePassportGroupViewState(searchParams).sortBy);
  const [sortOrder, setSortOrder] =
    useState<"asc" | "desc">(() => parsePassportGroupViewState(searchParams).sortOrder);
  const [page, setPage] = useState(() => parsePassportGroupViewState(searchParams).page);
  const pageSize = 50;
  const [viewMode, setViewMode] =
    useState<"table" | "docs">(() => parsePassportGroupViewState(searchParams).viewMode);
  const [navigationContextKey, setNavigationContextKey] = useState<{
    token: string;
    userId: string;
    groupId: string;
  } | null>(null);
  const navigationToken = navigationContextKey?.userId === currentUserId &&
    navigationContextKey.groupId === groupId
    ? navigationContextKey.token
    : null;
  const { data: submissionsView, isLoading, error, isFetching, isPlaceholderData, refetch: refetchSubmissions, } = useGroupSubmissionsView(groupId, {
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    include_deleted: includeDeleted,
    submission_filter: submissionFilter,
    sort_by: sortBy,
    sort_order: sortOrder,
    page,
    page_size: pageSize,
  });
  const data = submissionsView?.items;
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const token = createPassportNavigationToken();
      setNavigationContextKey(token && currentUserId
        ? { token, userId: currentUserId, groupId }
        : null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [groupId, currentUserId]);
  useEffect(() => {
    const viewState: PassportGroupViewState = {
      search: debouncedSearch,
      submissionFilter,
      sortBy,
      sortOrder,
      page,
      viewMode,
    };
    const href = buildPassportGroupHref(groupId, viewState, includeDeleted);
    const currentHref = `${window.location.pathname}${window.location.search}`;
    if (href !== currentHref)
      window.history.replaceState(null, "", href);
  }, [
    groupId,
    includeDeleted,
    page,
    debouncedSearch,
    sortBy,
    sortOrder,
    submissionFilter,
    viewMode,
  ]);
  useEffect(() => {
    if (!submissionsView || page <= submissionsView.total_pages)
      return;
    const timer = window.setTimeout(() => {
      setPage(Math.max(1, submissionsView.total_pages));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [page, submissionsView]);
  const expiryAlerts = useMemo(() => {
    return submissionsView?.expiry_alerts ?? [];
  }, [submissionsView?.expiry_alerts]);
  const filteredPassports = data ?? [];
  const detailNavigation: PassportDetailNavigationState = useMemo(() => ({
    token: navigationToken,
    groupId,
    includeDeleted,
    viewState: {
      search: debouncedSearch,
      submissionFilter,
      sortBy,
      sortOrder,
      page,
      viewMode,
    },
  }), [
    debouncedSearch,
    groupId,
    includeDeleted,
    navigationToken,
    page,
    sortBy,
    sortOrder,
    submissionFilter,
    viewMode,
  ]);
  const persistNavigationContext = useCallback(() => {
    if (!navigationToken || !currentUserId || !submissionsView)
      return;
    storePassportNavigationContext({
      token: navigationToken,
      userId: currentUserId,
      groupId,
      includeDeleted,
      viewState: detailNavigation.viewState,
      orderedSubmissionIds: submissionsView.ordered_submission_ids ??
        submissionsView.items.map((submission) => submission.id),
    });
  }, [
    currentUserId,
    detailNavigation.viewState,
    groupId,
    includeDeleted,
    navigationToken,
    submissionsView,
  ]);
  useEffect(() => {
    persistNavigationContext();
  }, [persistNavigationContext]);
  const passportDetailHref = (submissionId: string) => buildPassportDetailNavigationHref(submissionId, detailNavigation);
  return {
    includeDeleted,
    search,
    setSearch,
    debouncedSearch,
    setDebouncedSearch,
    submissionFilter,
    setSubmissionFilter,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    page,
    setPage,
    viewMode,
    setViewMode,
    submissionsView,
    data,
    isLoading,
    error,
    isFetching,
    isPlaceholderData,
    refetchSubmissions,
    expiryAlerts,
    filteredPassports,
    persistNavigationContext,
    passportDetailHref,
  };
}
