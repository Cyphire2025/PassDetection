import { env } from '@/core/config/env';

import { ApiError } from './api-error';

function assertSafeApiPath(path: string): void {
  if (
    !path.startsWith('/')
    || path.startsWith('//')
    || path.includes('#')
    || path.includes('\\')
    || /[\u0000-\u001f\u007f]/.test(path)
  ) {
    throw new Error('API paths must be root-relative.');
  }
  const pathname = path.split('?', 1)[0] ?? '';
  for (const segment of pathname.split('/').slice(1)) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      throw new Error('API paths must use valid percent encoding.');
    }
    if (
      decoded === '.'
      || decoded === '..'
      || decoded.includes('/')
      || decoded.includes('\\')
      || /[\u0000-\u001f\u007f]/.test(decoded)
    ) {
      throw new Error('API paths must not contain traversal or encoded separators.');
    }
  }
}

export function endpointUrl(path: string): string {
  assertSafeApiPath(path);
  return `${env.apiUrl}${path}`;
}

export function authorizedDocumentUrl(path: string): string {
  assertSafeApiPath(path);
  const apiBase = new URL(env.apiUrl);
  const parsedPath = new URL(path, apiBase.origin);
  const basePath = apiBase.pathname.replace(/\/$/, '');
  if (
    !path.startsWith('/')
    || path.startsWith('//')
    || parsedPath.origin !== apiBase.origin
    || (!parsedPath.pathname.startsWith(`${basePath}/mobile/`)
      && !parsedPath.pathname.startsWith('/mobile/'))
  ) {
    throw new ApiError('The download path was invalid.', 400, 'INVALID_DOWNLOAD_PATH', null);
  }
  return parsedPath.pathname.startsWith(`${basePath}/mobile/`)
    ? `${apiBase.origin}${parsedPath.pathname}${parsedPath.search}`
    : `${env.apiUrl}${parsedPath.pathname}${parsedPath.search}`;
}
