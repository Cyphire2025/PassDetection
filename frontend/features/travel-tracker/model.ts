import type { TrackerKind, TrackerPassenger } from "./types";

export const TRACKER_COPY = {
  visa: { label: "Visa", marked: "Visa applied", pending: "Visa pending", action: "Mark visa applied" },
  flight: { label: "Flight", marked: "Flight booked", pending: "Flight pending", action: "Mark flight booked" },
} as const;

export function isPassengerMarked(passenger: TrackerPassenger, track: TrackerKind) {
  return track === "visa" ? passenger.visa_applied : passenger.flight_booked;
}

export function trackerError(error: unknown) {
  if (typeof error === "object" && error !== null && "message" in error && typeof error.message === "string") {
    return error.message;
  }
  return "The request could not be completed. Please try again.";
}

export function formatTravelDate(value: string | null) {
  if (!value) return "Travel date not set";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
}

/** A CSV preview uses the same unique name matching rules as an Excel upload. */
export function pastedNamesFile(value: string) {
  const names = value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (names.length === 0) throw new Error("Paste at least one passenger name, one per line.");
  if (names.length > 1000) throw new Error("Paste up to 1,000 passenger names per batch. Split this list and preview each batch.");
  const csv = ["Name", ...names.map((name) => `"${name.replace(/"/g, '""')}"`)].join("\r\n");
  return new File([csv], "pasted-passengers.csv", { type: "text/csv" });
}
