import { collectCursorItems } from '@/features/content/data/cursor-pagination';

export type CursorPage<T> = { items: T[]; next_cursor: string | null };

export async function collectCursorPages<T extends { id: string }>(
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>,
  assertActive?: () => void,
): Promise<T[]> {
  return collectCursorItems(fetchPage, {
    itemKey: (item) => item.id,
    ...(assertActive ? { assertActive } : {}),
  });
}
