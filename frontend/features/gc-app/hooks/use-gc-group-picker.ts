"use client";

import { useState } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import {
  useClientCompanies,
  useClientCompanyMutations,
  useGcAppGroupMutations,
  useGcGroupSearch,
} from "./use-gc-app-admin";
import type { GcCompanyReference } from "../types";
import { gcAppErrorMessage } from "../utils";

export function useGcGroupPicker(agencyId: string | null) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerPage, setPickerPage] = useState(1);
  const [companySearch, setCompanySearch] = useState("");
  const [companyPage, setCompanyPage] = useState(1);
  const [pickerCompanyId, setPickerCompanyId] = useState("");
  const [pickerCompany, setPickerCompany] = useState<GcCompanyReference | null>(null);
  const [newCompanyName, setNewCompanyName] = useState("");
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [pendingCompanyRemoval, setPendingCompanyRemoval] = useState<GcCompanyReference | null>(null);
  const [companyRemovalConfirmation, setCompanyRemovalConfirmation] = useState("");
  const debouncedPickerSearch = useDebounce(pickerSearch, 300);
  const debouncedCompanySearch = useDebounce(companySearch, 300);
  const candidates = useGcGroupSearch(
    agencyId,
    { page: pickerPage, page_size: 20, search: debouncedPickerSearch },
    true,
    pickerOpen,
  );
  const companies = useClientCompanies(agencyId, debouncedCompanySearch, companyPage, 20, pickerOpen);
  const companyActions = useClientCompanyMutations(agencyId);
  const actions = useGcAppGroupMutations(agencyId);
  const companyItems = companies.data?.items ?? [];
  const activeCompanies = companyItems.filter((company) => company.status !== "inactive");
  const selectableCompanies = pickerCompany && !activeCompanies.some((company) => company.id === pickerCompany.id)
    ? [pickerCompany, ...activeCompanies]
    : activeCompanies;
  const pickerBusy = actions.add.isPending || companyActions.create.isPending || companyActions.remove.isPending;

  const openPicker = () => {
    setPickerError(null);
    setPendingCompanyRemoval(null);
    setCompanyRemovalConfirmation("");
    setPickerPage(1);
    setPickerOpen(true);
  };

  const closePicker = () => {
    if (pickerBusy) return;
    setPickerOpen(false);
    setPickerError(null);
    setPendingCompanyRemoval(null);
    setCompanyRemovalConfirmation("");
  };

  const removeCompany = async () => {
    if (!pendingCompanyRemoval || companyRemovalConfirmation.trim() !== pendingCompanyRemoval.name) return;
    setPickerError(null);
    try {
      await companyActions.remove.mutateAsync(pendingCompanyRemoval);
      if (pickerCompanyId === pendingCompanyRemoval.id) {
        setPickerCompanyId("");
        setPickerCompany(null);
      }
      setPendingCompanyRemoval(null);
      setCompanyRemovalConfirmation("");
    } catch (error) {
      setPickerError(gcAppErrorMessage(error, "The company/client could not be removed."));
    }
  };

  return {
    pickerOpen, closePicker, pickerBusy, pickerError, pickerCompanyId, setPickerCompanyId,
    setPickerCompany, selectableCompanies, companySearch, setCompanySearch, setCompanyPage,
    companies, newCompanyName, setNewCompanyName, setPickerError, companyActions,
    activeCompanies, setPendingCompanyRemoval, setCompanyRemovalConfirmation,
    pendingCompanyRemoval, companyRemovalConfirmation, removeCompany, pickerSearch,
    setPickerSearch, setPickerPage, candidates, actions, pickerCompany, setPickerOpen, openPicker
  };
}

export type GcGroupPicker = ReturnType<typeof useGcGroupPicker>;
