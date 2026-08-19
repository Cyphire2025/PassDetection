import {
  collectAndReplaceRoster,
  MOBILE_GROUP_PASSENGER_CAPACITY,
} from '../full-roster-sync';

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

test('collects the complete 10,000-passenger contract without a page-count ceiling', async () => {
  const all = Array.from(
    { length: MOBILE_GROUP_PASSENGER_CAPACITY },
    (_, index) => ({ id: `passenger-${index}` }),
  );
  const replace = jest.fn(async (_items: { id: string }[]) => undefined);
  let pages = 0;
  const items = await collectAndReplaceRoster(async (cursor) => {
    pages += 1;
    const offset = cursor ? Number(cursor) : 0;
    const page = all.slice(offset, offset + 100);
    return {
      items: page,
      next_cursor: offset + page.length < all.length ? String(offset + page.length) : null,
      total: all.length,
    };
  }, replace);

  expect(pages).toBe(100);
  expect(items).toHaveLength(MOBILE_GROUP_PASSENGER_CAPACITY);
  expect(replace).toHaveBeenCalledTimes(1);
  expect(replace).toHaveBeenCalledWith(items);
});

test('rejects over-cap totals, duplicate passengers, and cursor movement without progress', async () => {
  const replace = jest.fn(async () => undefined);
  await expect(collectAndReplaceRoster(async () => ({
    items: [],
    next_cursor: null,
    total: MOBILE_GROUP_PASSENGER_CAPACITY + 1,
  }), replace)).rejects.toThrow('advertised capacity');

  let duplicatePage = 0;
  await expect(collectAndReplaceRoster(async () => {
    duplicatePage += 1;
    return duplicatePage === 1
      ? { items: [{ id: 'duplicate' }], next_cursor: 'next', total: 2 }
      : { items: [{ id: 'duplicate' }], next_cursor: null, total: 2 };
  }, replace)).rejects.toThrow('repeated a passenger');

  await expect(collectAndReplaceRoster(async () => ({
    items: [],
    next_cursor: 'next',
    total: 1,
  }), replace)).rejects.toThrow('without progress');
  expect(replace).not.toHaveBeenCalled();
});

test('honors cancellation before publishing a fully collected roster', async () => {
  const replace = jest.fn(async () => undefined);
  let checks = 0;
  await expect(collectAndReplaceRoster(
    async (cursor) => ({
      items: [{ id: cursor ? 'second' : 'first' }],
      next_cursor: cursor ? null : 'next',
      total: 2,
    }),
    replace,
    MOBILE_GROUP_PASSENGER_CAPACITY,
    () => {
      checks += 1;
      if (checks >= 3) throw new Error('cancelled');
    },
  )).rejects.toThrow('cancelled');
  expect(replace).not.toHaveBeenCalled();
});
