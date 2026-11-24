"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { useExportSelectedGroups, usePassportGroups } from "../hooks/use-passports";

export function usePassportList() {
  const { data, isLoading, isFetching, error, refetch } = usePassportGroups();
  const exportSelected = useExportSelectedGroups();
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [reviewFilter, setReviewFilter] = useState("all");
  const [destinationFilter, setDestinationFilter] = useState("");
  const deferredDestinationFilter = useDeferredValue(destinationFilter);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const selectedGroupSet = useMemo(() => new Set(selectedGroups), [selectedGroups]);
  const summary = useMemo(() => {
    const groups = data ?? [];
    return groups.reduce((totals, group) => ({
      passports: totals.passports + group.total_passports,
      review: totals.review + group.pending_review_count,
      confirmedGroups: totals.confirmedGroups
        + (group.total_passports > 0 && group.confirmed_count === group.total_passports ? 1 : 0),
    }), { passports: 0, review: 0, confirmedGroups: 0 });
  }, [data]);
  const filteredGroups = useMemo(() => {
    const destinationQuery = deferredDestinationFilter.trim().toLocaleLowerCase();
    return (data ?? []).filter((group) => {
      if (statusFilter !== "all" && group.group_status !== statusFilter)
        return false;
      if (reviewFilter === "needs_review" && group.pending_review_count === 0)
        return false;
      if (reviewFilter === "has_passports" && group.total_passports === 0)
        return false;
      if (reviewFilter === "confirmed_only"
        && (group.total_passports === 0 || group.confirmed_count !== group.total_passports)) {
        return false;
      }
      if (destinationQuery
        && !(group.destination ?? "").toLocaleLowerCase().includes(destinationQuery)) {
        return false;
      }
      return true;
    });
  }, [data, deferredDestinationFilter, reviewFilter, statusFilter]);
  const toggleGroup = (groupId: string) => {
    setSelectedGroups((current) => current.includes(groupId)
      ? current.filter((id) => id !== groupId)
      : [...current, groupId]);
  };
  const resetFilters = () => {
    setStatusFilter("all");
    setReviewFilter("all");
    setDestinationFilter("");
  };
  return {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
    exportSelected,
    selectedGroups,
    setSelectedGroups,
    statusFilter,
    setStatusFilter,
    reviewFilter,
    setReviewFilter,
    destinationFilter,
    setDestinationFilter,
    isExportDialogOpen,
    setIsExportDialogOpen,
    selectedGroupSet,
    summary,
    filteredGroups,
    toggleGroup,
    resetFilters,
  };
}
export type PassportListModel = ReturnType<typeof usePassportList>;
