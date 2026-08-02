import { collectCursorPages } from '../pagination';

type Item = { id: string };

test('collects more than 100 assigned trips before authoritative cache deletion', async () => {
  const first = Array.from({ length: 100 }, (_, index) => ({ id: `trip-${index}` }));
  const second = Array.from({ length: 50 }, (_, index) => ({ id: `trip-${index + 100}` }));
  const calls: (string | null)[] = [];
  const result = await collectCursorPages<Item>(async (cursor) => {
    calls.push(cursor);
    return cursor ? { items: second, next_cursor: null } : { items: first, next_cursor: 'page-2' };
  }, 20);
  expect(result).toHaveLength(150);
  expect(calls).toEqual([null, 'page-2']);
});

test('deduplicates overlapping pages and rejects a repeated cursor', async () => {
  const result = await collectCursorPages<Item>(async (cursor) => cursor
    ? { items: [{ id: 'b' }], next_cursor: null }
    : { items: [{ id: 'a' }, { id: 'b' }], next_cursor: 'next' }, 5);
  expect(result.map((item) => item.id)).toEqual(['a', 'b']);

  await expect(collectCursorPages<Item>(async () => ({ items: [], next_cursor: 'same' }), 5)).rejects.toThrow('cursor');
});
