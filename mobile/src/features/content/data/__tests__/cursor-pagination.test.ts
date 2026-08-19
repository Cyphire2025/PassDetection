import { collectCursorItems, type CursorPage } from '../cursor-pagination';

describe('content cursor pagination', () => {
  it('collects every page without an accidental default page ceiling', async () => {
    const pages = new Map<string | null, CursorPage<number>>([
      [null, { items: [1, 2], next_cursor: 'two' }],
      ['two', { items: [3], next_cursor: 'three' }],
      ['three', { items: [4, 5], next_cursor: null }],
    ]);
    await expect(collectCursorItems(async (cursor) => pages.get(cursor)!)).resolves.toEqual([1, 2, 3, 4, 5]);
  });

  it('accepts an exact 10k domain capacity across more than twenty pages', async () => {
    const pageSize = 200;
    let calls = 0;
    const result = await collectCursorItems(
      async (cursor) => {
        calls += 1;
        const start = cursor ? Number(cursor) : 0;
        const items = Array.from(
          { length: pageSize },
          (_, offset) => ({ id: `passenger-${start + offset}` }),
        );
        const next = start + pageSize;
        return { items, next_cursor: next < 10_000 ? String(next) : null };
      },
      { maxItems: 10_000, itemKey: (item) => item.id },
    );

    expect(result).toHaveLength(10_000);
    expect(calls).toBe(50);
  });

  it('rejects cap plus one without publishing the over-cap page', async () => {
    const published: number[] = [];
    await expect(collectCursorItems(
      async (cursor) => (
        cursor === null
          ? { items: Array.from({ length: 10_000 }, (_, id) => id), next_cursor: 'overflow' }
          : { items: [10_000], next_cursor: null }
      ),
      {
        maxItems: 10_000,
        onPage: ({ items }) => {
          published.push(items.length);
        },
      },
    )).rejects.toThrow('advertised capacity');

    expect(published).toEqual([10_000]);
  });

  it('rejects a repeated cursor instead of committing a partial aggregate', async () => {
    await expect(
      collectCursorItems(async (cursor) => ({ items: [cursor ?? 'first'], next_cursor: 'repeat' })),
    ).rejects.toThrow('repeated');
  });

  it('propagates a later-page failure', async () => {
    let calls = 0;
    await expect(
      collectCursorItems(async () => {
        calls += 1;
        if (calls === 2) throw new Error('offline');
        return { items: ['cached'], next_cursor: 'next' };
      }),
    ).rejects.toThrow('offline');
  });

  it('publishes the first page before requesting later pages', async () => {
    let releaseFirstPage!: () => void;
    const firstPagePublished = new Promise<void>((resolve) => {
      releaseFirstPage = resolve;
    });
    let calls = 0;
    const published: number[][] = [];
    const collection = collectCursorItems(
      async (cursor) => {
        calls += 1;
        return cursor === null
          ? { items: [1, 2], next_cursor: 'next' }
          : { items: [3], next_cursor: null };
      },
      {
        onPage: async ({ items, pageNumber }) => {
          published.push([...items]);
          if (pageNumber === 1) await firstPagePublished;
        },
      },
    );

    await Promise.resolve();
    expect(published).toEqual([[1, 2]]);
    expect(calls).toBe(1);
    releaseFirstPage();
    await expect(collection).resolves.toEqual([1, 2, 3]);
    expect(published).toEqual([[1, 2], [1, 2, 3]]);
  });

  it('stops before another request when account-switch cancellation invalidates the context', async () => {
    let active = true;
    const fetchPage = jest.fn(async () => ({ items: ['first'], next_cursor: 'next' }));
    await expect(collectCursorItems(fetchPage, {
      assertActive: () => {
        if (!active) throw new Error('stale account context');
      },
      onPage: () => {
        active = false;
      },
    })).rejects.toThrow('stale account context');

    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it('rejects an empty non-terminal page that cannot make forward progress', async () => {
    await expect(collectCursorItems(async () => ({
      items: [],
      next_cursor: 'next',
    }))).rejects.toThrow('without advancing');
  });
});
