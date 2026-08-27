import {
  FaceScanStartGate,
  faceScanStartDisposition,
} from '../face-scan-start-gate';

it('coalesces rapid Face Scan starts before React can publish the starting state', async () => {
  let release!: () => void;
  const response = new Promise<void>((resolve) => { release = resolve; });
  const operation = jest.fn(async () => {
    await response;
    return 'clear_idempotency_key' as const;
  });
  const gate = new FaceScanStartGate(() => 'request-a');

  const first = gate.run(operation);
  const second = gate.run(operation);
  expect(first).toBe(second);
  expect(operation).toHaveBeenCalledTimes(1);
  release();
  await first;
});

it('reuses one idempotency key after an ambiguous response and rotates after a definitive one', async () => {
  const ids = ['request-a', 'request-b'];
  const gate = new FaceScanStartGate(() => ids.shift()!);
  const observed: string[] = [];

  await gate.run(async (requestId) => {
    observed.push(requestId);
    return 'retain_idempotency_key';
  });
  await gate.run(async (requestId) => {
    observed.push(requestId);
    return 'clear_idempotency_key';
  });
  await gate.run(async (requestId) => {
    observed.push(requestId);
    return 'clear_idempotency_key';
  });

  expect(observed).toEqual(['request-a', 'request-a', 'request-b']);
});

it('rotates the key after intentional cancellation resets the logical attempt', async () => {
  const ids = ['request-a', 'request-b'];
  const gate = new FaceScanStartGate(() => ids.shift()!);
  await gate.run(async () => 'retain_idempotency_key');
  gate.reset();
  let observed = '';
  await gate.run(async (requestId) => {
    observed = requestId;
    return 'clear_idempotency_key';
  });
  expect(observed).toBe('request-b');
});

it('retains the same start identity when background aborts ambiguous session creation', async () => {
  const ids = ['request-a', 'request-b'];
  const gate = new FaceScanStartGate(() => ids.shift()!);
  const observed: string[] = [];

  await gate.run(async (requestId) => {
    observed.push(requestId);
    return faceScanStartDisposition({
      sessionCreated: false,
      operationAborted: true,
      transportAmbiguous: false,
    });
  });
  await gate.run(async (requestId) => {
    observed.push(requestId);
    return 'clear_idempotency_key';
  });

  expect(observed).toEqual(['request-a', 'request-a']);
});
