import type { TourPassenger } from "@/features/operations/api/operations.api";

export type OfflinePassengerSnapshot = Pick<
  TourPassenger,
  "id" | "client_name" | "client_email" | "client_phone" | "departure_city"
>;

type OfflinePassengerSnapshotSource = OfflinePassengerSnapshot;

export function toOfflinePassengerSnapshot(
  passenger: OfflinePassengerSnapshotSource,
): OfflinePassengerSnapshot {
  return {
    id: passenger.id,
    client_name: passenger.client_name,
    client_email: passenger.client_email,
    client_phone: passenger.client_phone,
    departure_city: passenger.departure_city,
  };
}

export function sanitizeOfflinePassengerSnapshots(
  value: unknown,
): OfflinePassengerSnapshot[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = requiredString(item.id);
    const clientName = requiredString(item.client_name);
    if (!id || !clientName) return [];

    return [
      toOfflinePassengerSnapshot({
        id,
        client_name: clientName,
        client_email: nullableString(item.client_email),
        client_phone: nullableString(item.client_phone),
        departure_city: nullableString(item.departure_city),
      }),
    ];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requiredString(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function nullableString(value: unknown) {
  return typeof value === "string" ? value : null;
}
