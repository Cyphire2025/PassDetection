import { mergeProgressiveItemsById } from '../progressive-page';

test('fresh progressive pages replace matching stale rows and retain unseen rows until completion', () => {
  expect(mergeProgressiveItemsById(
    [{ id: 'fresh', value: 2 }],
    [{ id: 'fresh', value: 1 }, { id: 'unseen', value: 1 }],
  )).toEqual([
    { id: 'fresh', value: 2 },
    { id: 'unseen', value: 1 },
  ]);
});
