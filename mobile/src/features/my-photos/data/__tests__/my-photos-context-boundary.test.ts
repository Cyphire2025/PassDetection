import type { MyPhotosContext } from '../my-photos-context';
import { runWhenMyPhotosContextCurrent } from '../my-photos-context';

function staleContext(): MyPhotosContext {
  const controller = new AbortController();
  controller.abort(new Error('Account changed.'));
  return {
    namespace: 'tenant.account-a',
    sessionId: 'session-a',
    agencyId: 'tenant',
    principalId: 'account-a',
    role: 'passenger',
    tripId: '11111111-1111-4111-8111-111111111111',
    passengerId: '22222222-2222-4222-8222-222222222222',
    signal: controller.signal,
  };
}

describe('My Photos durable-write boundary', () => {
  it('does not invoke a database-opening write after the account context is stale', () => {
    const openAndWrite = jest.fn(async () => undefined);

    const result = runWhenMyPhotosContextCurrent(staleContext(), openAndWrite);

    expect(result).toBeNull();
    expect(openAndWrite).not.toHaveBeenCalled();
  });
});
