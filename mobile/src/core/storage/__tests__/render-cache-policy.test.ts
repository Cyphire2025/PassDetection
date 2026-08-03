import { shouldPurgeDiskCacheForAccountTransition } from '../render-cache-policy';

test('does not repeat the startup disk purge for the first restored account', () => {
  expect(shouldPurgeDiskCacheForAccountTransition({
    previousAccount: null,
    nextAccount: 'agency:account-a',
    hasActivatedAccount: false,
  })).toBe(false);
});

test('purges disk state at later account and logout boundaries', () => {
  expect(shouldPurgeDiskCacheForAccountTransition({
    previousAccount: 'agency:account-a',
    nextAccount: 'agency:account-b',
    hasActivatedAccount: true,
  })).toBe(true);
  expect(shouldPurgeDiskCacheForAccountTransition({
    previousAccount: 'agency:account-a',
    nextAccount: null,
    hasActivatedAccount: true,
  })).toBe(true);
  expect(shouldPurgeDiskCacheForAccountTransition({
    previousAccount: null,
    nextAccount: 'agency:account-b',
    hasActivatedAccount: true,
  })).toBe(true);
});
