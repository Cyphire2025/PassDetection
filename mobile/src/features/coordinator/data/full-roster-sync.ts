export type RosterPage<T> = {
  items: T[];
  next_cursor: string | null;
  total: number;
};

export const MOBILE_GROUP_PASSENGER_CAPACITY = 10_000;

export async function collectAndReplaceRoster<T extends { id: string }>(
  fetchPage: (cursor: string | null) => Promise<RosterPage<T>>,
  replace: (items: T[]) => Promise<void>,
  maximumItems = MOBILE_GROUP_PASSENGER_CAPACITY,
  assertActive?: () => void,
): Promise<T[]> {
  if (!Number.isSafeInteger(maximumItems) || maximumItems < 1) {
    throw new Error('The coordinator roster capacity was invalid.');
  }
  const items: T[] = [];
  const seenIds = new Set<string>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let expectedTotal: number | null = null;
  do {
    assertActive?.();
    const page = await fetchPage(cursor);
    assertActive?.();
    if (!Number.isSafeInteger(page.total) || page.total < 0 || page.total > maximumItems) {
      throw new Error('The coordinator roster exceeded its advertised capacity.');
    }
    if (expectedTotal === null) expectedTotal = page.total;
    else if (page.total !== expectedTotal) {
      throw new Error('The coordinator roster changed during synchronization.');
    }
    if (items.length + page.items.length > maximumItems) {
      throw new Error('The coordinator roster exceeded its advertised capacity.');
    }
    for (const item of page.items) {
      if (seenIds.has(item.id)) {
        throw new Error('The coordinator roster repeated a passenger during synchronization.');
      }
      seenIds.add(item.id);
      items.push(item);
    }
    if (page.next_cursor !== null && page.items.length === 0) {
      throw new Error('The coordinator roster cursor advanced without progress.');
    }
    if (
      page.next_cursor !== null
      && (
        page.next_cursor.length === 0
        || page.next_cursor === cursor
        || seenCursors.has(page.next_cursor)
      )
    ) {
      throw new Error('The coordinator roster cursor did not advance.');
    }
    cursor = page.next_cursor;
    if (cursor) seenCursors.add(cursor);
  } while (cursor);

  if (expectedTotal !== items.length) throw new Error('The coordinator roster synchronization was incomplete.');
  assertActive?.();
  await replace(items);
  assertActive?.();
  return items;
}
