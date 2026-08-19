export type VaultQuotaReservation = Readonly<{
  namespace: string;
  maximumEncryptedBytes: number;
  materializedBytes: () => number;
}>;

function safeBytes(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative safe integer.`);
  }
  return value;
}

/**
 * Process-local serial lane and reservation book for concurrent vault writers. Every admission
 * decision runs through `exclusive`, while each accepted writer contributes its remaining
 * worst-case growth until the caller releases it.
 */
export class VaultQuotaReservationBook {
  private readonly reservations = new Map<string, VaultQuotaReservation>();
  private tail: Promise<void> = Promise.resolve();

  exclusive<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.tail.then(operation, operation);
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  reservedGrowth(namespace?: string): number {
    let total = 0;
    for (const reservation of this.reservations.values()) {
      if (namespace !== undefined && reservation.namespace !== namespace) continue;
      const maximum = safeBytes(
        reservation.maximumEncryptedBytes,
        'Maximum reserved ciphertext size',
      );
      const materialized = safeBytes(
        reservation.materializedBytes(),
        'Materialized ciphertext size',
      );
      total += Math.max(0, maximum - materialized);
      if (!Number.isSafeInteger(total)) {
        throw new Error('Reserved vault growth exceeded the safe integer range.');
      }
    }
    return total;
  }

  add(id: string, reservation: VaultQuotaReservation): void {
    if (!id || !reservation.namespace) {
      throw new Error('A vault quota reservation requires an identity and account namespace.');
    }
    safeBytes(reservation.maximumEncryptedBytes, 'Maximum reserved ciphertext size');
    if (this.reservations.has(id)) throw new Error('A vault quota reservation already exists.');
    this.reservations.set(id, reservation);
  }

  release(id: string): void {
    this.reservations.delete(id);
  }
}
