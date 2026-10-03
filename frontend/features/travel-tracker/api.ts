import apiClient from "@/lib/api/client";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import type {
  TrackerFilters, TrackerGroups, TrackerImportPreview, TrackerKind,
  TrackerMarkRequest, TrackerMarkResult, TrackerRoster, TrackerStatus,
} from "./types";

const base = "/api/v1/travel-tracker";
const groupUrl = (id: string) => `${base}/groups/${encodeURIComponent(id)}`;

export const travelTrackerApi = {
  async groups(search: string, page: number, signal?: AbortSignal) {
    const { data } = await apiClient.get<TrackerGroups>(`${base}/groups`, {
      params: { search: search.trim() || undefined, page, page_size: 24 }, signal,
    });
    return data;
  },
  async roster(id: string, filters: TrackerFilters, signal?: AbortSignal) {
    const { data } = await apiClient.get<TrackerRoster>(groupUrl(id), {
      params: { ...filters, search: filters.search.trim() || undefined }, signal,
    });
    return data;
  },
  async mark(id: string, request: TrackerMarkRequest) {
    const { data } = await apiClient.patch<TrackerMarkResult>(`${groupUrl(id)}/marks`, request);
    return data;
  },
  async preview(id: string, file: File, track: TrackerKind, marked: boolean) {
    const form = new FormData();
    form.append("file", file);
    form.append("track", track);
    form.append("marked", String(marked));
    const { data } = await apiClient.post<TrackerImportPreview>(`${groupUrl(id)}/import/preview`, form, {
      headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000,
    });
    return data;
  },
  async export(id: string, name: string, track: TrackerKind, status: TrackerStatus) {
    await downloadStreamedResponse({
      url: `${groupUrl(id)}/export`, params: { track, status },
      suggestedFilename: `${name.replace(/[^a-zA-Z0-9_-]+/g, "_")}_${track}_${status}.xlsx`,
    });
  },
};
