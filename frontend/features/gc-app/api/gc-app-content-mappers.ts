import type { GcAnnouncement, GcCommonDocument, StructuredItinerary } from "../types";
import type { RawItineraryVersion, RawCommonDocument, RawAnnouncement } from "./gc-app-wire.types";

export function normalizeItinerary(raw: RawItineraryVersion | null): StructuredItinerary {
  if (!raw) {
    return {
      version_id: null,
      status: "new",
      title: "Group itinerary",
      days: [],
      draft_revision: "new",
      published_version: 0,
      published_at: null,
      updated_at: null,
    };
  }
  return {
    version_id: raw.id,
    status: raw.status,
    title: raw.title,
    days: raw.days.map((day, dayIndex) => ({
      client_id: `day-${day.day_number}-${dayIndex}`,
      day_number: day.day_number,
      date: day.date ?? "",
      title: day.title ?? `Day ${day.day_number}`,
      items: [...day.items].sort((a, b) => a.sort_order - b.sort_order).map((item, itemIndex) => ({
        client_id: `item-${day.day_number}-${item.sort_order}-${itemIndex}`,
        time: itineraryTime(item.starts_at),
        title: item.title,
        description: item.description ?? "",
        location: item.location_name ?? "",
      })),
    })),
    draft_revision: raw.id,
    published_version: raw.version,
    published_at: raw.published_at,
    updated_at: raw.updated_at,
  };
}

function itineraryTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function itineraryStartsAt(dayDate: string, time: string): string | null {
  if (!dayDate || !time) return null;
  const date = new Date(`${dayDate}T${time}:00`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function normalizeDocument(raw: RawCommonDocument): GcCommonDocument {
  return {
    id: raw.id,
    title: raw.display_name,
    category: raw.category as GcCommonDocument["category"],
    filename: raw.original_filename,
    version: raw.version,
    is_published: raw.status === "published",
    available_from: raw.available_from,
    available_until: raw.available_until,
    updated_at: raw.updated_at,
    sort_order: raw.sort_order,
  };
}

export function normalizeAnnouncement(raw: RawAnnouncement): GcAnnouncement {
  return {
    id: raw.id,
    title: raw.title,
    body: raw.message,
    priority: raw.priority,
    is_published: raw.status === "published",
    available_from: raw.available_from,
    available_until: raw.available_until,
    version: raw.version,
    updated_at: raw.updated_at,
  };
}
