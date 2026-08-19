import { apiDownloadToFile } from '@/core/api/client';

import {
  loadManagerDocumentPreview,
  purgeManagerDocumentPreviews,
} from '../manager-document-preview';

const mockDeleteDirectory = jest.fn();
const mockDirectory = {
  create: jest.fn(),
  delete: mockDeleteDirectory,
  exists: true,
  uri: 'file:///cache/gc-manager-previews/',
};
const mockFileConstructor = jest.fn();
const temporaryFile = {
  delete: jest.fn(),
  exists: false,
  move: jest.fn(),
  name: 'preview-id.download',
  open: jest.fn(),
  size: 0,
  uri: 'file:///cache/gc-manager-previews/preview-id.download',
};

jest.mock('expo-crypto', () => ({ randomUUID: () => 'preview-id' }));
jest.mock('expo-file-system', () => ({
  Directory: jest.fn(() => mockDirectory),
  File: function MockFile(...arguments_: unknown[]) {
    return mockFileConstructor(...arguments_);
  },
  FileMode: { ReadOnly: 'r' },
  Paths: { cache: 'file:///cache/' },
}));
jest.mock('@/core/api/client', () => ({ apiDownloadToFile: jest.fn() }));
jest.mock('@/core/storage/ios-backup', () => ({
  nativePathForAppPrivateFileUri: (uri: string) => uri.replace('file://', ''),
}));

const mockedApiDownload = jest.mocked(apiDownloadToFile);

beforeEach(() => {
  jest.clearAllMocks();
  mockDirectory.exists = true;
  temporaryFile.exists = false;
  temporaryFile.size = 0;
  mockFileConstructor.mockReturnValue(temporaryFile);
});

test('purges every crash-left manager preview from its dedicated cache directory', async () => {
  await expect(purgeManagerDocumentPreviews()).resolves.toBeUndefined();

  expect(mockDeleteDirectory).toHaveBeenCalledTimes(1);
});

test('an account or app lifecycle purge invalidates a preview download already in flight', async () => {
  let resolveResponse!: (response: Awaited<ReturnType<typeof apiDownloadToFile>>) => void;
  mockedApiDownload.mockReturnValueOnce(new Promise((resolve) => {
    resolveResponse = resolve;
  }));

  const preview = loadManagerDocumentPreview(
    '55555555-5555-4555-8555-555555555555',
    '22222222-2222-4222-8222-222222222222',
    'visa',
  );
  await purgeManagerDocumentPreviews();
  temporaryFile.exists = true;
  temporaryFile.size = 5;
  resolveResponse({
    headers: {
      'content-length': '5',
      'content-type': 'application/pdf',
    },
    redirects: [],
    status: 200,
  });

  await expect(preview).rejects.toThrow('Document preview was cancelled.');
  expect(temporaryFile.delete).toHaveBeenCalledTimes(1);
  expect(temporaryFile.move).not.toHaveBeenCalled();
});

test('streams a bounded preview to native cache and validates only a small signature prefix', async () => {
  const handle = {
    close: jest.fn(),
    readBytes: jest.fn(() => Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2d])),
  };
  const destination = {
    exists: true,
    name: 'preview-id.pdf',
    uri: 'file:///cache/gc-manager-previews/preview-id.pdf',
  };
  temporaryFile.exists = true;
  temporaryFile.size = 5;
  temporaryFile.open.mockReturnValue(handle);
  mockFileConstructor
    .mockReturnValueOnce(temporaryFile)
    .mockReturnValueOnce(destination);
  mockedApiDownload.mockResolvedValue({
    headers: {
      'content-length': '5',
      'content-type': 'application/pdf',
    },
    redirects: [],
    status: 200,
  });

  await expect(loadManagerDocumentPreview(
    '55555555-5555-4555-8555-555555555555',
    '22222222-2222-4222-8222-222222222222',
    'visa',
  )).resolves.toEqual({ file: destination, contentType: 'application/pdf' });

  expect(mockedApiDownload).toHaveBeenCalledWith(
    expect.stringContaining('/preview'),
    expect.objectContaining({
      destinationPath: '/cache/gc-manager-previews/preview-id.download',
      maximumBytes: 25 * 1024 * 1024,
    }),
  );
  expect(handle.readBytes).toHaveBeenCalledWith(12);
  expect(handle.close).toHaveBeenCalledTimes(1);
  expect(temporaryFile.move).toHaveBeenCalledWith(destination);
});
