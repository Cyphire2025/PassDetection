import { VaultQuotaReservationBook } from '../vault-quota-reservations';

describe('concurrent vault quota reservation book', () => {
  test('admits only one of two concurrent writes that would exceed an aggregate account limit', async () => {
    const book = new VaultQuotaReservationBook();
    const admitted: string[] = [];
    const admit = (id: string) => book.exclusive(async () => {
      if (40 + book.reservedGrowth('account-a') + 40 > 100) {
        throw new Error('account quota');
      }
      book.add(id, {
        namespace: 'account-a',
        maximumEncryptedBytes: 40,
        materializedBytes: () => 0,
      });
      admitted.push(id);
    });

    const results = await Promise.allSettled([admit('first'), admit('second')]);
    expect(results.map((result) => result.status)).toEqual(['fulfilled', 'rejected']);
    expect(admitted).toEqual(['first']);
    expect(book.reservedGrowth('account-a')).toBe(40);
  });

  test('tracks only remaining growth and releases reservations idempotently', () => {
    const book = new VaultQuotaReservationBook();
    let materialized = 10;
    book.add('write-a', {
      namespace: 'account-a',
      maximumEncryptedBytes: 50,
      materializedBytes: () => materialized,
    });
    book.add('write-b', {
      namespace: 'account-b',
      maximumEncryptedBytes: 30,
      materializedBytes: () => 0,
    });

    expect(book.reservedGrowth('account-a')).toBe(40);
    expect(book.reservedGrowth()).toBe(70);
    materialized = 50;
    expect(book.reservedGrowth('account-a')).toBe(0);
    book.release('write-a');
    book.release('write-a');
    expect(book.reservedGrowth()).toBe(30);
  });
});
