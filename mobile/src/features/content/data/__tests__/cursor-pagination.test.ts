import { collectCursorItems, type CursorPage } from '../cursor-pagination';

describe('content cursor pagination', () => {
  it('collects every bounded page', async () => {
    const pages = new Map<string | null, CursorPage<number>>([
      [null, { items: [1, 2], next_cursor: 'two' }],
      ['two', { items: [3], next_cursor: 'three' }],
      ['three', { items: [4, 5], next_cursor: null }],
    ]);
    await expect(collectCursorItems(async (cursor) => pages.get(cursor)!)).resolves.toEqual([1, 2, 3, 4, 5]);
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
});
