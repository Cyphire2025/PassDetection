import { validateNativeDocumentDownload } from '../vault';

const PDF = 'application/pdf';

function response(
  status: number,
  headers: Readonly<Record<string, string>>,
) {
  return { status, headers };
}

describe('native bounded document transport contract', () => {
  test('accepts an exact full response before native-file encryption', () => {
    expect(() => validateNativeDocumentDownload(
      response(200, {
        'content-type': 'application/pdf; charset=binary',
        'content-length': '4',
      }),
      PDF,
      4,
      0,
    )).not.toThrow();
  });

  test('accepts chunked transfer metadata while the final native file owns exact-size proof', () => {
    expect(() => validateNativeDocumentDownload(
      response(200, { 'content-type': PDF }),
      PDF,
      4,
      0,
    )).not.toThrow();
  });

  test('requires an exact 206 range when encrypted staging resumes', () => {
    expect(() => validateNativeDocumentDownload(
      response(206, {
        'content-type': PDF,
        'content-length': '2',
        'content-range': 'bytes 2-3/4',
      }),
      PDF,
      4,
      2,
    )).not.toThrow();
  });

  test.each([
    [200, 'bytes 2-3/4', 'server did not honor'],
    [206, 'bytes 1-2/4', 'range did not match'],
  ])('rejects invalid resume response %#', (status, contentRange, message) => {
    expect(() => validateNativeDocumentDownload(
      response(status, {
        'content-type': PDF,
        'content-length': '2',
        'content-range': contentRange,
      }),
      PDF,
      4,
      2,
    )).toThrow(message);
  });

  test('rejects type and declared-length mismatches before reading plaintext chunks', () => {
    expect(() => validateNativeDocumentDownload(
      response(200, {
        'content-type': 'image/png',
        'content-length': '4',
      }),
      PDF,
      4,
      0,
    )).toThrow('type did not match');

    expect(() => validateNativeDocumentDownload(
      response(200, {
        'content-type': PDF,
        'content-length': '5',
      }),
      PDF,
      4,
      0,
    )).toThrow('length did not match');
  });
});
