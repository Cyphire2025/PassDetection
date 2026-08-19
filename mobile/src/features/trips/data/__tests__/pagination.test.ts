import { collectCursorPages } from '../pagination';

type Item = { id: string };

test('collects more than 100 assigned trips before authoritative cache deletion', async () => {
  const first = Array.from({ length: 100 }, (_, index) => ({ id: `trip-${index}` }));
  const second = Array.from({ length: 50 }, (_, index) => ({ id: `trip-${index + 100}` }));
  const calls: (string | null)[] = [];
  const result = await collectCursorPages<Item>(async (cursor) => {
    calls.push(cursor);
    return cursor ? { items: second, next_cursor: null } : { items: first, next_cursor: 'page-2' };
  });
  expect(result).toHaveLength(150);
  expect(calls).toEqual([null, 'page-2']);
});

test('rejects overlapping rows and a repeated cursor instead of trusting a moving snapshot', async () => {
  await expect(collectCursorPages<Item>(async (cursor) => cursor
    ? { items: [{ id: 'b' }], next_cursor: null }
    : { items: [{ id: 'a' }, { id: 'b' }], next_cursor: 'next' }))
    .rejects.toThrow('repeated synchronized content');

  await expect(collectCursorPages<Item>(async () => ({ items: [{ id: 'a' }], next_cursor: 'same' })))
    .rejects.toThrow('cursor');
});

test('collects 10k assigned trips across more than twenty pages', async () => {
  let calls = 0;
  const items = await collectCursorPages<Item>(async (cursor) => {
    calls += 1;
    const start = cursor ? Number(cursor) : 0;
    const page = Array.from({ length: 100 }, (_, offset) => ({ id: `trip-${start + offset}` }));
    const next = start + page.length;
    return { items: page, next_cursor: next < 10_000 ? String(next) : null };
  });

  expect(items).toHaveLength(10_000);
  expect(calls).toBe(100);
});
