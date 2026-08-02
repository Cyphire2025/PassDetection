export type RosterPage<T> = {
  items: T[];
  next_cursor: string | null;
  total: number;
};

export async function collectAndReplaceRoster<T extends { id: string }>(
  fetchPage: (cursor: string | null) => Promise<RosterPage<T>>,
  replace: (items: T[]) => Promise<void>,
  maximumPages = 25,
): Promise<T[]> {
  const items: T[] = [];
  const seenIds = new Set<string>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let expectedTotal: number | null = null;
  let pages = 0;
  do {
    if (pages >= maximumPages) throw new Error('The coordinator roster exceeded the offline synchronization limit.');
    const page = await fetchPage(cursor);
    if (expectedTotal === null) expectedTotal = page.total;
    else if (page.total !== expectedTotal) throw new Error('The coordinator roster changed during synchronization.');
    for (const item of page.items) {
      if (!seenIds.has(item.id)) {
        seenIds.add(item.id);
        items.push(item);
      }
    }
    pages += 1;
    if (page.next_cursor && seenCursors.has(page.next_cursor)) throw new Error('The coordinator roster cursor did not advance.');
    cursor = page.next_cursor;
    if (cursor) seenCursors.add(cursor);
  } while (cursor);

  if (expectedTotal !== items.length) throw new Error('The coordinator roster synchronization was incomplete.');
  await replace(items);
  return items;
}
