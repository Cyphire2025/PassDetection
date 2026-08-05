import { openDocumentResponseReader, readResponseBytesBounded } from '../vault';

const PDF = 'application/pdf';

function streamedResponse(
  chunks: readonly Uint8Array[],
  options: {
    status?: number;
    contentLength?: string | null;
    contentRange?: string | null;
    failAfterChunks?: number;
  } = {},
): Response {
  let cursor = 0;
  const reader = {
    cancel: jest.fn(async () => undefined),
    read: jest.fn(async () => {
      if (options.failAfterChunks !== undefined && cursor >= options.failAfterChunks) {
        throw new Error('simulated interrupted transfer');
      }
      if (cursor >= chunks.length) return { done: true, value: undefined };
      const value = chunks[cursor];
      cursor += 1;
      return { done: false, value };
    }),
  };
  const headers = new Headers({ 'content-type': PDF });
  if (options.contentLength !== undefined && options.contentLength !== null) {
    headers.set('content-length', options.contentLength);
  }
  if (options.contentRange !== undefined && options.contentRange !== null) {
    headers.set('content-range', options.contentRange);
  }
  return {
    status: options.status ?? 200,
    headers,
    body: { getReader: () => reader },
    arrayBuffer: async () => {
      throw new Error('stream reader should be used');
    },
  } as unknown as Response;
}

function bufferedResponse(bytes: Uint8Array): Response {
  return {
    status: 200,
    headers: new Headers({
      'content-type': PDF,
      'content-length': String(bytes.byteLength),
    }),
    body: null,
    arrayBuffer: jest.fn(async () => bytes.buffer.slice(
      bytes.byteOffset,
      bytes.byteOffset + bytes.byteLength,
    )),
  } as unknown as Response;
}

describe('bounded document stream transport', () => {
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('accepts an unknown Content-Length while enforcing the signed byte ceiling', async () => {
    const response = streamedResponse([
      Uint8Array.from([1, 2]),
      Uint8Array.from([3, 4]),
    ], { contentLength: null });

    await expect(readResponseBytesBounded(
      response,
      4,
      PDF,
      jest.fn(),
    )).resolves.toEqual(Uint8Array.from([1, 2, 3, 4]));
  });

  it('opens React Native buffered responses as bounded vault chunks', async () => {
    const bytes = new Uint8Array(300_000).fill(7);
    const reader = await openDocumentResponseReader(bufferedResponse(bytes), bytes.byteLength);

    const first = await reader.read();
    const second = await reader.read();
    const end = await reader.read();

    expect(first.done).toBe(false);
    expect(first.value).toHaveLength(256 * 1024);
    expect(second.done).toBe(false);
    expect(second.value).toHaveLength(bytes.byteLength - 256 * 1024);
    expect(end).toEqual({ done: true, value: undefined });
  });

  it('rejects a truncated React Native buffered response before vault writes begin', async () => {
    await expect(openDocumentResponseReader(
      bufferedResponse(Uint8Array.from([1, 2, 3])),
      4,
    )).rejects.toThrow('before all signed bytes were received');
  });

  it('resumes a mid-stream failure at the exact committed offset', async () => {
    jest.useFakeTimers();
    const initial = streamedResponse([
      Uint8Array.from([1, 2]),
      Uint8Array.from([3, 4]),
    ], { failAfterChunks: 1 });
    const resumed = streamedResponse([
      Uint8Array.from([3, 4]),
    ], {
      status: 206,
      contentLength: '2',
      contentRange: 'bytes 2-3/4',
    });
    const resume = jest.fn(async () => resumed);

    const pending = readResponseBytesBounded(initial, 4, PDF, resume);
    await jest.runAllTimersAsync();

    await expect(pending).resolves.toEqual(Uint8Array.from([1, 2, 3, 4]));
    expect(resume).toHaveBeenCalledTimes(1);
    expect(resume).toHaveBeenCalledWith(2);
  });

  it('rejects a resumed response with a mismatched Content-Range', async () => {
    jest.useFakeTimers();
    const initial = streamedResponse([
      Uint8Array.from([1, 2]),
    ], { failAfterChunks: 1 });
    const invalidResume = streamedResponse([
      Uint8Array.from([3, 4]),
    ], {
      status: 206,
      contentLength: '2',
      contentRange: 'bytes 1-2/4',
    });

    const pending = readResponseBytesBounded(
      initial,
      4,
      PDF,
      async () => invalidResume,
    );
    const rejection = expect(pending).rejects.toThrow('range did not match');
    await jest.runAllTimersAsync();

    await rejection;
  });

  it('cancels and rejects when a stream exceeds its signed maximum', async () => {
    const response = streamedResponse([
      Uint8Array.from([1, 2, 3]),
      Uint8Array.from([4, 5]),
    ]);

    await expect(readResponseBytesBounded(
      response,
      4,
      PDF,
      jest.fn(),
    )).rejects.toThrow('exceeded its allowed size');
  });

  it('does not resume an aborted transfer', async () => {
    jest.useFakeTimers();
    const controller = new AbortController();
    const initial = streamedResponse([
      Uint8Array.from([1, 2]),
    ], { failAfterChunks: 1 });
    const resume = jest.fn();
    const pending = readResponseBytesBounded(
      initial,
      4,
      PDF,
      resume,
      controller.signal,
    );
    const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    controller.abort();
    await jest.runAllTimersAsync();

    await rejection;
    expect(resume).not.toHaveBeenCalled();
  });
});
