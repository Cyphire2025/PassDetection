import { FeedbackIntentLane } from '../feedback-intent-lane';

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

test('serializes same-asset feedback and assigns each intent a monotonic revision', async () => {
  const intents = new FeedbackIntentLane();
  const firstResponse = deferred<string>();
  const firstStarted = deferred<void>();
  const order: string[] = [];

  const first = intents.run('asset-a', async (revision) => {
    order.push(`first-start:${revision}`);
    firstStarted.resolve();
    const result = await firstResponse.promise;
    order.push('first-finish');
    return result;
  });
  const second = intents.run('asset-a', async (revision) => {
    order.push(`second-start:${revision}`);
    return 'second';
  });
  await firstStarted.promise;

  expect(order).toEqual(['first-start:1']);
  firstResponse.resolve('first');
  await expect(Promise.all([first, second])).resolves.toEqual(['first', 'second']);
  expect(order).toEqual(['first-start:1', 'first-finish', 'second-start:2']);
});

test('allows independent assets to proceed concurrently and resets boundary revisions', async () => {
  const intents = new FeedbackIntentLane();
  const revisions = await Promise.all([
    intents.run('asset-a', async (revision) => revision),
    intents.run('asset-b', async (revision) => revision),
  ]);
  expect(revisions).toEqual([1, 1]);

  intents.reset();
  await expect(intents.run('asset-a', async (revision) => revision)).resolves.toBe(1);
});
