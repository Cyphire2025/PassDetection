export type CursorPage<T> = { items: T[]; next_cursor: string | null };

export async function collectCursorPages<T extends { id: string }>(
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>,
  maximumPages: number,
): Promise<T[]> {
  const items: T[] = [];
  const seenIds = new Set<string>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let pages = 0;
  do {
    if (pages >= maximumPages) throw new Error('The assigned trip list exceeded the mobile synchronization limit.');
    const result = await fetchPage(cursor);
    for (const item of result.items) {
      if (!seenIds.has(item.id)) {
        seenIds.add(item.id);
        items.push(item);
      }
    }
    pages += 1;
    if (result.next_cursor && seenCursors.has(result.next_cursor)) throw new Error('The assigned trip cursor did not advance.');
    cursor = result.next_cursor;
    if (cursor) seenCursors.add(cursor);
  } while (cursor);
  return items;
}
