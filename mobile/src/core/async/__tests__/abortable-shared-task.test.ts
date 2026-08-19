import { AbortableSharedTaskRegistry } from '../abortable-shared-task';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

test('coalesces concurrent consumers onto one expensive task', async () => {
  const registry = new AbortableSharedTaskRegistry<string, number>();
  const pending = deferred<number>();
  const task = jest.fn(() => pending.promise);

  const first = registry.run('same', task);
  const second = registry.run('same', task);
  await Promise.resolve();
  expect(task).toHaveBeenCalledTimes(1);

  pending.resolve(42);
  await expect(Promise.all([first, second])).resolves.toEqual([42, 42]);
});

test('keeps shared work alive while at least one consumer remains', async () => {
  const registry = new AbortableSharedTaskRegistry<string, string>();
  const pending = deferred<string>();
  const firstController = new AbortController();
  let taskSignal: AbortSignal | null = null;
  const task = jest.fn((signal: AbortSignal) => {
    taskSignal = signal;
    return pending.promise;
  });

  const first = registry.run('same', task, firstController.signal);
  const second = registry.run('same', task);
  await Promise.resolve();
  firstController.abort(new Error('first screen closed'));

  await expect(first).rejects.toThrow('first screen closed');
  expect(taskSignal).not.toBeNull();
  expect((taskSignal as unknown as AbortSignal).aborted).toBe(false);
  pending.resolve('ready');
  await expect(second).resolves.toBe('ready');
});

test('aborts the underlying task when every consumer cancels', async () => {
  const registry = new AbortableSharedTaskRegistry<string, never>();
  const firstController = new AbortController();
  const secondController = new AbortController();
  let taskSignal: AbortSignal | null = null;
  const task = jest.fn((signal: AbortSignal) => {
    taskSignal = signal;
    return new Promise<never>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
  });

  const first = registry.run('same', task, firstController.signal);
  const second = registry.run('same', task, secondController.signal);
  await Promise.resolve();
  firstController.abort(new Error('first closed'));
  secondController.abort(new Error('second closed'));

  await expect(first).rejects.toThrow('first closed');
  await expect(second).rejects.toThrow('second closed');
  expect(taskSignal).not.toBeNull();
  expect((taskSignal as unknown as AbortSignal).aborted).toBe(true);
});

test('does not retain a failed task as a poisoned cache entry', async () => {
  const registry = new AbortableSharedTaskRegistry<string, number>();
  const task = jest.fn()
    .mockRejectedValueOnce(new Error('damaged'))
    .mockResolvedValueOnce(7);

  await expect(registry.run('same', task)).rejects.toThrow('damaged');
  await expect(registry.run('same', task)).resolves.toBe(7);
  expect(task).toHaveBeenCalledTimes(2);
});
