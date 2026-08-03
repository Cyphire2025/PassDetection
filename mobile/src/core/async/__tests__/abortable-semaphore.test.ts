import { AbortableSemaphore } from '../abortable-semaphore';

test('removes an aborted waiter without consuming or leaking a permit', async () => {
  const semaphore = new AbortableSemaphore(1);
  const releaseFirst = await semaphore.acquire();
  const controller = new AbortController();
  const waiting = semaphore.acquire(controller.signal);

  controller.abort();
  await expect(waiting).rejects.toMatchObject({ name: 'AbortError' });
  releaseFirst();

  const releaseNext = await semaphore.acquire();
  expect(typeof releaseNext).toBe('function');
  releaseNext();
});

test('hands a released permit directly to the oldest live waiter', async () => {
  const semaphore = new AbortableSemaphore(1);
  const releaseFirst = await semaphore.acquire();
  const order: string[] = [];
  const second = semaphore.acquire().then((release) => {
    order.push('second');
    return release;
  });
  const third = semaphore.acquire().then((release) => {
    order.push('third');
    return release;
  });

  releaseFirst();
  const releaseSecond = await second;
  expect(order).toEqual(['second']);
  releaseSecond();
  const releaseThird = await third;
  expect(order).toEqual(['second', 'third']);
  releaseThird();
});
