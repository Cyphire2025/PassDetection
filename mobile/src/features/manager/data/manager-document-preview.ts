import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import { apiResponse } from '@/core/api/client';

import type { ManagerDocumentMode } from './manager-operations';

const PREVIEW_ROOT = 'gc-manager-previews';
const MAX_PREVIEW_BYTES = 25 * 1024 * 1024;
const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
]);

export type ManagerPreview = Readonly<{
  file: File;
  contentType: string;
}>;

function previewRoot(): Directory {
  const root = new Directory(Paths.cache, PREVIEW_ROOT);
  if (!root.exists) root.create({ idempotent: true, intermediates: true });
  return root;
}

function extension(contentType: string): string {
  if (contentType === 'application/pdf') return 'pdf';
  if (contentType === 'image/jpeg') return 'jpg';
  if (contentType === 'image/png') return 'png';
  if (contentType === 'image/webp') return 'webp';
  throw new Error('The server returned an unsupported document type.');
}

function validateSignature(bytes: Uint8Array, contentType: string): void {
  const valid = contentType === 'application/pdf'
    ? new TextDecoder().decode(bytes.subarray(0, 5)) === '%PDF-'
    : contentType === 'image/jpeg'
      ? bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
      : contentType === 'image/png'
        ? bytes[0] === 0x89 && new TextDecoder().decode(bytes.subarray(1, 4)) === 'PNG'
        : contentType === 'image/webp'
          ? new TextDecoder().decode(bytes.subarray(0, 4)) === 'RIFF'
            && new TextDecoder().decode(bytes.subarray(8, 12)) === 'WEBP'
          : false;
  if (!valid) throw new Error('The document content did not match its declared type.');
}

export async function loadManagerDocumentPreview(
  tripId: string,
  passengerId: string,
  documentType: Exclude<ManagerDocumentMode, 'all'>,
  signal?: AbortSignal,
): Promise<ManagerPreview> {
  const response = await apiResponse(
    `/mobile/manager/groups/${tripId}/passengers/${passengerId}/documents/${documentType}/preview`,
    {
      accept: 'application/pdf,image/jpeg,image/png,image/webp',
      timeoutMs: 5_000,
      ...(signal ? { signal } : {}),
    },
  );
  const contentType = (response.headers.get('content-type') ?? '').toLowerCase();
  const normalizedContentType = contentType.split(';', 1)[0]?.trim() ?? '';
  if (!ALLOWED_CONTENT_TYPES.has(normalizedContentType)) {
    throw new Error('The server returned an unsupported document type.');
  }
  const declaredLength = response.headers.get('content-length');
  if (!declaredLength || !/^\d+$/.test(declaredLength)) {
    throw new Error('The document response did not include a safe size.');
  }
  const expectedBytes = Number(declaredLength);
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes < 1 || expectedBytes > MAX_PREVIEW_BYTES) {
    throw new Error('The document is outside the mobile preview limit.');
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (signal?.aborted) throw signal.reason ?? new Error('Document preview was cancelled.');
  if (bytes.byteLength !== expectedBytes) {
    throw new Error('The document response was incomplete.');
  }
  validateSignature(bytes, normalizedContentType);

  const file = new File(
    previewRoot(),
    `${Crypto.randomUUID()}.${extension(normalizedContentType)}`,
  );
  file.create({ overwrite: false, intermediates: true });
  try {
    file.write(bytes);
    return { file, contentType: normalizedContentType };
  } catch (error) {
    if (file.exists) file.delete();
    throw error;
  }
}

export function removeManagerDocumentPreview(preview: ManagerPreview | null): void {
  if (!preview) return;
  const root = new Directory(Paths.cache, PREVIEW_ROOT);
  if (new File(root, preview.file.name).uri !== preview.file.uri) {
    throw new Error('Refusing to remove an unmanaged preview file.');
  }
  if (preview.file.exists) preview.file.delete();
}
