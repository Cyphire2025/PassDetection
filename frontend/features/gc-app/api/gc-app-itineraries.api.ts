import apiClient from "@/lib/api/client";
import type { StructuredItinerary } from "../types";
import type { GcMutationRequestConfig, RawItineraryVersion } from "./gc-app-wire.types";
import { ROOT, agencyParams } from "./gc-app-transport";
import { normalizeItinerary, itineraryStartsAt } from "./gc-app-content-mappers";

export const gcAppItinerariesApi = {
  saveItineraryDraft: async (
    agencyId: string | null,
    groupId: string,
    itinerary: StructuredItinerary,
    expectedAccessRevision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/drafts`,
      {
        title: itinerary.title,
        days: itinerary.days.map((day, dayIndex) => ({
          day_number: dayIndex + 1,
          date: day.date || null,
          title: day.title || null,
          items: day.items.map((item, itemIndex) => ({
            title: item.title,
            description: item.description || null,
            starts_at: itineraryStartsAt(day.date, item.time),
            ends_at: null,
            location_name: item.location || null,
            latitude: null,
            longitude: null,
            sort_order: itemIndex,
          })),
        })),
        expected_access_revision: expectedAccessRevision,
      },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },

  publishItinerary: async (
    agencyId: string | null,
    groupId: string,
    versionId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/${versionId}/publish`,
      undefined,
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },

  unpublishItinerary: async (
    agencyId: string | null,
    groupId: string,
    versionId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<StructuredItinerary> => {
    const { data } = await apiClient.post<RawItineraryVersion>(
      `${ROOT}/groups/${groupId}/itineraries/${versionId}/unpublish`,
      undefined,
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeItinerary(data);
  },
};
