export type CursorPage<T> = {
  items: T[];
  next_cursor: string | null;
};

export async function collectCursorItems<T>(
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>,
  options: { maxPages?: number; maxItems?: number } = {},
): Promise<T[]> {
  const maxPages = options.maxPages ?? 20;
  const maxItems = options.maxItems ?? 4_000;
  const seenCursors = new Set<string>();
  const items: T[] = [];
  let cursor: string | null = null;

  for (let pageNumber = 0; pageNumber < maxPages; pageNumber += 1) {
    const page = await fetchPage(cursor);
    items.push(...page.items);
    if (items.length > maxItems) {
      throw new Error('The synchronized content exceeded the mobile safety limit.');
    }
    if (!page.next_cursor) return items;
    if (page.next_cursor === cursor || seenCursors.has(page.next_cursor)) {
      throw new Error('The server repeated a content pagination cursor.');
    }
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }

  throw new Error('The synchronized content exceeded the mobile page limit.');
}
