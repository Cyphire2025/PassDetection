"use client";

import { useState } from "react";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { operationsApi } from "../api/operations.api";
import { useRoomingActions, useRoomingPriorityFields, useRoomingWorkspace } from "./use-operations";
import { roomingErrorMessage } from "../components/rooming-error-message";

type HotelTab = "allocation" | "checkins";

export function useRoomingWorkspaceController(groupId: string) {
  const { data, isLoading, error } = useRoomingWorkspace(groupId);
  const priorityFields = useRoomingPriorityFields(groupId);
  const actions = useRoomingActions(groupId);
  const [selectedHotelId, setSelectedHotelId] = useState<string | null>(null);
  const [showHotelDialog, setShowHotelDialog] = useState(false);
  const [showHotelEditDialog, setShowHotelEditDialog] = useState(false);
  const [hotelTab, setHotelTab] = useState<HotelTab>("allocation");
  const [actionError, setActionError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const activeHotel = (
    data?.hotels.find((hotel) => hotel.id === selectedHotelId)
    ?? data?.hotels[0]
    ?? null
  );

  const exportHotel = async () => {
    if (!activeHotel || activeHotel.rooms.length === 0 || isExporting) return;
    setActionError(null);
    setIsExporting(true);
    try {
      await operationsApi.exportRoomingHotel(activeHotel.id, activeHotel.hotel_name);
    } catch (exportError) {
      if (isDownloadCancelled(exportError)) return;
      setActionError(
        roomingErrorMessage(
          exportError,
          "The hotel rooming workbook could not be generated. Please try again.",
        ),
      );
    } finally {
      setIsExporting(false);
    }
  };

  return {
    data, isLoading, error, priorityFields, actions, activeHotel,
    selectedHotelId, setSelectedHotelId,
    showHotelDialog, setShowHotelDialog, showHotelEditDialog, setShowHotelEditDialog,
    hotelTab, setHotelTab, actionError, setActionError, isExporting, exportHotel,
  };
}
