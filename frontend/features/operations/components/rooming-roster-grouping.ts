import type { RoomingPassenger } from "../api/operations.api";

export const ROOMING_NOT_PROVIDED_KEY = "__rooming_not_provided__";
export const ROOMING_NOT_PROVIDED_LABEL = "Not provided";

export interface RoomingRosterGroup {
  key: string;
  label: string;
  passengers: RoomingPassenger[];
}

export interface RoomingRosterValueOption {
  key: string;
  label: string;
  count: number;
}

const ROOMING_COLLATOR = new Intl.Collator("en", {
  numeric: true,
  sensitivity: "base",
  usage: "sort",
});

export function roomingRosterValue(
  value: string | null | undefined,
): string | null {
  const cleaned = String(value ?? "").trim().replace(/\s+/g, " ");
  return cleaned || null;
}

export function roomingRosterValueKey(
  value: string | null | undefined,
): string {
  const cleaned = roomingRosterValue(value);
  return cleaned
    ? cleaned.normalize("NFKC").toLocaleLowerCase("en")
    : ROOMING_NOT_PROVIDED_KEY;
}

export function sortRoomingRosterPassengers(
  passengers: RoomingPassenger[],
  direction: "asc" | "desc" = "asc",
): RoomingPassenger[] {
  const multiplier = direction === "desc" ? -1 : 1;
  return [...passengers].sort((left, right) => {
    const nameComparison = ROOMING_COLLATOR.compare(
      left.client_name,
      right.client_name,
    );
    if (nameComparison !== 0) return nameComparison * multiplier;
    return left.passenger_id.localeCompare(right.passenger_id) * multiplier;
  });
}

export function groupRoomingRosterPassengers(
  passengers: RoomingPassenger[],
  valuesByPassenger: Record<string, string | null | undefined>,
  direction: "asc" | "desc" = "asc",
): RoomingRosterGroup[] {
  const groupsByKey = new Map<string, RoomingRosterGroup>();
  for (const passenger of sortRoomingRosterPassengers(passengers, direction)) {
    const rawValue = roomingRosterValue(
      valuesByPassenger[passenger.passenger_id],
    );
    const key = roomingRosterValueKey(rawValue);
    const existing = groupsByKey.get(key);
    if (existing) {
      existing.passengers.push(passenger);
      continue;
    }
    groupsByKey.set(key, {
      key,
      label: rawValue ?? ROOMING_NOT_PROVIDED_LABEL,
      passengers: [passenger],
    });
  }
  const multiplier = direction === "desc" ? -1 : 1;
  return Array.from(groupsByKey.values()).sort((left, right) => {
    if (left.key === ROOMING_NOT_PROVIDED_KEY) return 1;
    if (right.key === ROOMING_NOT_PROVIDED_KEY) return -1;
    return ROOMING_COLLATOR.compare(left.label, right.label) * multiplier;
  });
}

export function roomingRosterValueOptions(
  passengers: RoomingPassenger[],
  valuesByPassenger: Record<string, string | null | undefined>,
): RoomingRosterValueOption[] {
  return groupRoomingRosterPassengers(passengers, valuesByPassenger).map(
    ({ key, label, passengers: groupedPassengers }) => ({
      key,
      label,
      count: groupedPassengers.length,
    }),
  );
}
