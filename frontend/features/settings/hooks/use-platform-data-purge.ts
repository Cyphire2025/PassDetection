"use client";

import { useRef, useState } from "react";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

type PurgePassportDataResponse = {
  deleted_client_groups: number;
  deleted_passport_submissions: number;
  deleted_processing_jobs: number;
  deleted_notifications: number;
  deleted_audit_logs: number;
  deleted_storage_objects: number;
  deleted_whatsapp_broadcast_groups: number;
  deleted_whatsapp_recipients: number;
  deleted_whatsapp_support_contacts: number;
  deleted_whatsapp_message_logs: number;
  deleted_whatsapp_delivery_states: number;
};

export const DELETE_CONFIRMATION = "DELETE ALL DATA";

export function usePlatformDataPurge(canPurge: boolean) {
  const [confirmation, setConfirmation] = useState("");
  const [isPurging, setIsPurging] = useState(false);
  const [purgeError, setPurgeError] = useState<string | null>(null);
  const [purgeResult, setPurgeResult] =
    useState<PurgePassportDataResponse | null>(null);
  const [isPurgeDialogOpen, setIsPurgeDialogOpen] = useState(false);

  const isConfirmed = confirmation === DELETE_CONFIRMATION;
  const purgeInFlight = useRef(false);
  const handlePurgePassportData = async () => {
    if (!canPurge || !isConfirmed || isPurging || purgeInFlight.current) return;
    purgeInFlight.current = true;

    setIsPurging(true);
    setPurgeError(null);
    setPurgeResult(null);
    try {
      const { data } = await apiClient.delete<PurgePassportDataResponse>(
        API_ENDPOINTS.admin.passportData,
      );
      setPurgeResult(data);
      setConfirmation("");
      setIsPurgeDialogOpen(false);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Could not delete passport data.";
      setPurgeError(message);
    } finally {
      purgeInFlight.current = false;
      setIsPurging(false);
    }
  };

  return {
    confirmation, setConfirmation, isConfirmed, isPurging, purgeError,
    purgeResult, isPurgeDialogOpen, setIsPurgeDialogOpen, handlePurgePassportData,
  };
}

export type PlatformDataPurgeController = ReturnType<typeof usePlatformDataPurge>;
