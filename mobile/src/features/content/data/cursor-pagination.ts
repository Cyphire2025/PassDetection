export type CursorPage<T> = {
  items: T[];
  next_cursor: string | null;
};

export type CursorPageProgress<T> = Readonly<{
  items: readonly T[];
  pageItems: readonly T[];
  pageNumber: number;
  nextCursor: string | null;
}>;

type CursorCollectionOptions<T> = Readonly<{
  /** A domain/contract capacity, not an arbitrary client-side pagination limit. */
  maxItems?: number;
  /** Optional protocol guard for a resource whose server contract advertises one. */
  maxPages?: number;
  /** Re-validates immutable account/session ownership around every awaited boundary. */
  assertActive?: () => void;
  /** Rejects duplicate records across page boundaries when the resource exposes a stable key. */
  itemKey?: (item: T) => string;
  /** Publishes a defensive cumulative snapshot after each validated page. */
  onPage?: (progress: CursorPageProgress<T>) => void | Promise<void>;
}>;

export async function collectCursorItems<T>(
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>,
  options: CursorCollectionOptions<T> = {},
): Promise<T[]> {
  if (options.maxItems !== undefined
      && (!Number.isSafeInteger(options.maxItems) || options.maxItems < 0)) {
    throw new Error('The cursor item capacity was invalid.');
  }
  if (options.maxPages !== undefined
      && (!Number.isSafeInteger(options.maxPages) || options.maxPages < 1)) {
    throw new Error('The cursor page capacity was invalid.');
  }
  const seenCursors = new Set<string>();
  const seenItemKeys = new Set<string>();
  const items: T[] = [];
  let cursor: string | null = null;
  let pageNumber = 0;

  while (true) {
    options.assertActive?.();
    const page = await fetchPage(cursor);
    options.assertActive?.();
    pageNumber += 1;
    for (const item of page.items) {
      const itemKey = options.itemKey?.(item);
      if (itemKey !== undefined) {
        if (!itemKey || seenItemKeys.has(itemKey)) {
          throw new Error('The server repeated synchronized content across cursor pages.');
        }
        seenItemKeys.add(itemKey);
      }
      items.push(item);
    }
    if (options.maxItems !== undefined && items.length > options.maxItems) {
      throw new Error('The synchronized content exceeded its advertised capacity.');
    }
    if (options.maxPages !== undefined && pageNumber > options.maxPages) {
      throw new Error('The synchronized content exceeded its advertised page capacity.');
    }
    if (page.next_cursor && page.items.length === 0) {
      throw new Error('The server returned a cursor without advancing the synchronized content.');
    }
    if (page.next_cursor
        && (page.next_cursor === cursor || seenCursors.has(page.next_cursor))) {
      throw new Error('The server repeated a content pagination cursor.');
    }
    const progress = {
      items: [...items],
      pageItems: [...page.items],
      pageNumber,
      nextCursor: page.next_cursor,
    } satisfies CursorPageProgress<T>;
    await options.onPage?.(progress);
    options.assertActive?.();
    if (!page.next_cursor) return items;
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }
}
