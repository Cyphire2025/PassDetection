import { collectAndReplaceRoster } from '../full-roster-sync';

test('collects and commits a 1,500-passenger roster only after every page succeeds', async () => {
  const all = Array.from({ length: 1500 }, (_, index) => ({ id: `passenger-${index}` }));
  const replaced: { id: string }[][] = [];
  const items = await collectAndReplaceRoster(async (cursor) => {
    const offset = cursor ? Number(cursor) : 0;
    const page = all.slice(offset, offset + 200);
    const next = offset + page.length < all.length ? String(offset + page.length) : null;
    return { items: page, next_cursor: next, total: all.length };
  }, async (complete) => { replaced.push(complete); });
  expect(items).toHaveLength(1500);
  expect(replaced).toHaveLength(1);
  expect(replaced[0]).toHaveLength(1500);
});

test('does not replace the prior cache after an interrupted page or repeated cursor', async () => {
  const replace = jest.fn(async () => undefined);
  let calls = 0;
  await expect(collectAndReplaceRoster(async () => {
    calls += 1;
    if (calls === 2) throw new Error('offline');
    return { items: [{ id: 'a' }], next_cursor: 'next', total: 2 };
  }, replace)).rejects.toThrow('offline');
  expect(replace).not.toHaveBeenCalled();

  await expect(collectAndReplaceRoster(async () => ({ items: [], next_cursor: 'same', total: 1 }), replace)).rejects.toThrow('cursor');
  expect(replace).not.toHaveBeenCalled();
});
