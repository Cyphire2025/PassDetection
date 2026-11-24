/** Keep a client-side page within the current filtered or refreshed collection. */
export function clampPageOffset(offset: number, total: number, pageSize: number): number {
  return Math.min(offset, Math.max(0, Math.ceil(total / pageSize) - 1) * pageSize);
}
