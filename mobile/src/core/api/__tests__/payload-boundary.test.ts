import { z } from 'zod';

import { ApiError, apiRequest } from '../client';

jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));

const contract = z.object({ ok: z.literal(true) }).strict();

function responseFromChunks(chunks: Uint8Array[], headers?: HeadersInit): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  }), {
    status: 200,
    headers: {
      'content-type': 'application/json',
      ...headers,
    },
  });
}

describe('bounded JSON response handling', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('accepts a valid chunked response when Content-Length is omitted', async () => {
    const encoder = new TextEncoder();
    jest.spyOn(globalThis, 'fetch').mockResolvedValue(responseFromChunks([
      encoder.encode('{"ok"'),
      encoder.encode(':true}'),
    ]));

    await expect(apiRequest('/mobile/me', {
      authenticated: false,
      schema: contract,
    })).resolves.toEqual({ ok: true });
  });

  it('stops an omitted-length response once the streamed byte cap is exceeded', async () => {
    const oversizedChunk = new Uint8Array(2 * 1024 * 1024 + 1);
    oversizedChunk.fill(0x20);
    jest.spyOn(globalThis, 'fetch').mockResolvedValue(responseFromChunks([oversizedChunk]));

    await expect(apiRequest('/mobile/trips', {
      authenticated: false,
      schema: contract,
    })).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PAYLOAD_TOO_LARGE',
      status: 502,
    });
  });

  it('rejects an oversized declared length before consuming the body', async () => {
    const encoder = new TextEncoder();
    const response = responseFromChunks([encoder.encode('{"ok":true}')], {
      'content-length': String(2 * 1024 * 1024 + 1),
    });
    const getReader = jest.spyOn(response.body!, 'getReader');
    jest.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await expect(apiRequest('/mobile/trips', {
      authenticated: false,
      schema: contract,
    })).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PAYLOAD_TOO_LARGE',
      status: 502,
    });
    expect(getReader).not.toHaveBeenCalled();
  });

  it('cancels the native stream when an omitted-length response exceeds the cap', async () => {
    const cancel = jest.fn();
    const oversizedChunk = new Uint8Array(2 * 1024 * 1024 + 1);
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(oversizedChunk);
      },
      cancel,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
    jest.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await expect(apiRequest('/mobile/trips', {
      authenticated: false,
      schema: contract,
    })).rejects.toMatchObject<Partial<ApiError>>({
      code: 'PAYLOAD_TOO_LARGE',
      status: 502,
    });
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it('normalizes malformed success JSON to the mobile API error contract', async () => {
    const encoder = new TextEncoder();
    jest.spyOn(globalThis, 'fetch').mockResolvedValue(responseFromChunks([
      encoder.encode('{not-json'),
    ]));

    await expect(apiRequest('/mobile/trips', {
      authenticated: false,
      schema: contract,
    })).rejects.toMatchObject<Partial<ApiError>>({
      code: 'INVALID_RESPONSE',
      status: 502,
    });
  });
});
