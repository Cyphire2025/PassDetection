"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { PassportSubmission } from "@/types/passport.types";
import { useGroupSubmissionsView } from "../hooks/use-passports";
import { buildPassportDetailNavigationHref, isPassportNavigationKeyboardTarget, parsePassportDetailNavigation, readPassportNavigationContext, type PassportDetailNavigationState, type StoredPassportNavigationContext } from "../utils/passport-group-navigation";

export function usePassportDetailNavigation(data: Pick<PassportSubmission, "id" | "group_id"> | undefined, navigationQuery: string, userId: string | undefined, isImageEditorOpen: boolean) {
  const router = useRouter();
  const navigationFromUrl = useMemo(() => parsePassportDetailNavigation(new URLSearchParams(navigationQuery)), [navigationQuery]);
  const [storedNavigation, setStoredNavigation] =
    useState<StoredPassportNavigationContext | null>(null);
  const navigationGroupMatches = Boolean(
    data
    && navigationFromUrl
    && data.group_id === navigationFromUrl.groupId,
  );
  const {
    data: fallbackNavigationView,
  } = useGroupSubmissionsView(
    navigationFromUrl?.groupId ?? "",
    {
      ...(navigationFromUrl?.viewState.search
        ? { search: navigationFromUrl.viewState.search }
        : {}),
      include_deleted: navigationFromUrl?.includeDeleted ?? false,
      submission_filter:
        navigationFromUrl?.viewState.submissionFilter ?? "all",
      sort_by: navigationFromUrl?.viewState.sortBy ?? "name",
      sort_order: navigationFromUrl?.viewState.sortOrder ?? "asc",
      page: 1,
      page_size: 1,
    },
    navigationGroupMatches,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!navigationFromUrl || !userId || !navigationGroupMatches) {
        setStoredNavigation(null);
        return;
      }
      setStoredNavigation(
        readPassportNavigationContext({
          token: navigationFromUrl.token,
          userId,
          groupId: navigationFromUrl.groupId,
        }),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    userId,
    navigationFromUrl,
    navigationGroupMatches,
  ]);

  const validStoredNavigation =
    storedNavigation
    && storedNavigation.userId === userId
    && storedNavigation.groupId === data?.group_id
      ? storedNavigation
      : null;
  const activeNavigation: PassportDetailNavigationState | null =
    validStoredNavigation ?? (navigationGroupMatches ? navigationFromUrl : null);
  const orderedSubmissionIds = validStoredNavigation?.orderedSubmissionIds
    ?? fallbackNavigationView?.ordered_submission_ids
    ?? [];
  const navigationIndex = data
    ? orderedSubmissionIds.indexOf(data.id)
    : -1;
  const previousSubmissionId = navigationIndex > 0
    ? orderedSubmissionIds[navigationIndex - 1]
    : null;
  const nextSubmissionId =
    navigationIndex >= 0 && navigationIndex < orderedSubmissionIds.length - 1
      ? orderedSubmissionIds[navigationIndex + 1]
      : null;
  const previousHref =
    previousSubmissionId && activeNavigation
      ? buildPassportDetailNavigationHref(previousSubmissionId, activeNavigation)
      : null;
  const nextHref =
    nextSubmissionId && activeNavigation
      ? buildPassportDetailNavigationHref(nextSubmissionId, activeNavigation)
      : null;

  useEffect(() => {
    const handleArrowNavigation = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented
        || event.altKey
        || event.ctrlKey
        || event.metaKey
        || event.shiftKey
        || isImageEditorOpen
        || isPassportNavigationKeyboardTarget(event.target)
      ) {
        return;
      }
      const destination = event.key === "ArrowLeft"
        ? previousHref
        : event.key === "ArrowRight"
          ? nextHref
          : null;
      if (!destination) return;
      event.preventDefault();
      router.push(destination);
    };
    window.addEventListener("keydown", handleArrowNavigation);
    return () => window.removeEventListener("keydown", handleArrowNavigation);
  }, [isImageEditorOpen, nextHref, previousHref, router]);

  return { activeNavigation, orderedSubmissionIds, navigationIndex, previousHref, nextHref };
}
