/**
 * Publishes a validated fresh prefix immediately while retaining older unseen
 * rows until the complete authoritative result replaces the query value.
 */
export function mergeProgressiveItemsById<T extends { id: string }>(
  freshPrefix: readonly T[],
  previous: readonly T[] = [],
): T[] {
  const freshIds = new Set(freshPrefix.map((item) => item.id));
  return [
    ...freshPrefix,
    ...previous.filter((item) => !freshIds.has(item.id)),
  ];
}
