import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Pdf from 'react-native-pdf';

import { ApiError } from '@/core/api/client';
import { NativeFileDownloadError } from '@/core/api/native-file-download';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import {
  decryptDocumentForViewing,
  isLocalOfflineCiphertextError,
  releaseTemporaryView,
  removeTemporaryView,
} from '@/core/storage/vault';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import {
  cacheDocument,
  getDocument,
  recordOfflineDocumentOpened,
} from '@/features/content/data/content-repository';
import { useCoordinatorTripStore } from '@/features/coordinator/state/coordinator-trip-store';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

type TemporaryView = Awaited<ReturnType<typeof decryptDocumentForViewing>>;
type ViewerFailure = { message: string; retryable: boolean; supportCode: string };
type OpenOperation = { key: string; promise: Promise<void>; controller: AbortController };

class TerminalDocumentViewerError extends Error {}

/**
 * Projects native, provider, and policy failures into a deliberately small,
 * non-sensitive support vocabulary. Raw messages can contain private paths or
 * upstream diagnostics and must never cross the UI boundary.
 */
function viewerSupportCode(error: unknown): string {
  if (error instanceof TerminalDocumentViewerError) return 'DOCUMENT_UNAVAILABLE';
  if (isLocalOfflineCiphertextError(error)) return 'DOCUMENT_LOCAL_COPY_DAMAGED';
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) return 'DOCUMENT_ACCESS_DENIED';
    if (error.status === 404 || error.status === 410) return 'DOCUMENT_UNAVAILABLE';
    if (error.status === 409) return 'DOCUMENT_VERSION_CHANGED';
    if (error.status === 408 || error.status === 425) return 'DOCUMENT_REQUEST_TIMEOUT';
    if (error.status === 413 || error.code === 'PAYLOAD_TOO_LARGE') return 'DOCUMENT_TOO_LARGE';
    if (error.status === 429) return 'DOCUMENT_RATE_LIMITED';
    if (error.status >= 500) return 'DOCUMENT_SERVICE_UNAVAILABLE';
    return `DOCUMENT_HTTP_${Math.max(400, Math.min(499, Math.trunc(error.status)))}`;
  }
  if (error instanceof NativeFileDownloadError) {
    switch (error.kind) {
      case 'interrupted': return 'DOCUMENT_NATIVE_INTERRUPTED';
      case 'local_storage': return 'DOCUMENT_LOCAL_STORAGE_FAILED';
      case 'network': return 'DOCUMENT_NETWORK_FAILED';
      case 'response_wrapper': return 'DOCUMENT_NATIVE_RESPONSE_FAILED';
      case 'timeout': return 'DOCUMENT_REQUEST_TIMEOUT';
      default: return 'DOCUMENT_NATIVE_FAILED';
    }
  }

  const name = error instanceof Error ? error.name : '';
  const message = error instanceof Error ? error.message : '';
  if (name === 'DocumentTransferIntegrityError') {
    if (/content type/i.test(message)) return 'DOCUMENT_CONTENT_TYPE_MISMATCH';
    if (/content (?:length|range)|resume/i.test(message)) return 'DOCUMENT_RANGE_MISMATCH';
    if (/ended before|length|size/i.test(message)) return 'DOCUMENT_LENGTH_MISMATCH';
    if (/checksum/i.test(message)) return 'DOCUMENT_CHECKSUM_MISMATCH';
    return 'DOCUMENT_INTEGRITY_FAILED';
  }
  if (name === 'NativeFileDownloadTooLargeError') return 'DOCUMENT_TOO_LARGE';
  if (/download interrupted/i.test(message)) return 'DOCUMENT_NATIVE_INTERRUPTED';
  if (/timed?\s*out/i.test(message) || name === 'TimeoutError') return 'DOCUMENT_REQUEST_TIMEOUT';
  if (/network|connection|failed to fetch|request error/i.test(message) || error instanceof TypeError) {
    return 'DOCUMENT_NETWORK_FAILED';
  }
  if (/not enough free|storage quota/i.test(message)) return 'DOCUMENT_DEVICE_STORAGE_FULL';
  if (/secure storage|file|directory|enoent|eacces|permission/i.test(message)) {
    return 'DOCUMENT_LOCAL_STORAGE_FAILED';
  }
  if (/authorized document metadata|metadata.*match/i.test(message)) {
    return 'DOCUMENT_METADATA_MISMATCH';
  }
  if (/authorization.*(?:invalid|expired)/i.test(message)) {
    return 'DOCUMENT_AUTHORIZATION_INVALID';
  }
  if (/checksum/i.test(message)) return 'DOCUMENT_CHECKSUM_MISMATCH';
  if (/content type/i.test(message)) return 'DOCUMENT_CONTENT_TYPE_MISMATCH';
  if (/ended before|content length|size did not match/i.test(message)) {
    return 'DOCUMENT_LENGTH_MISMATCH';
  }
  if (/range|resume/i.test(message)) return 'DOCUMENT_RANGE_MISMATCH';
  if (/still being prepared/i.test(message)) return 'DOCUMENT_PREPARING';
  if (/authentication|required|active account|ownership boundary/i.test(message)) {
    return 'DOCUMENT_ACCOUNT_BOUNDARY';
  }
  return 'DOCUMENT_INTERNAL_FAILURE';
}

function viewerFailure(error: unknown): ViewerFailure {
  const localCiphertextFailure = isLocalOfflineCiphertextError(error);
  const internalMessage = error instanceof Error ? error.message : '';
  const terminalApiFailure = error instanceof ApiError && (
    error.status === 403
    || (
      (error.status === 404 || error.status === 410)
      && ['NOT_FOUND', 'DOCUMENT_GONE', 'DOCUMENT_REVOKED'].includes(error.code)
    )
  );
  const terminalMessage = (
    /no longer available|revoked|not authorized|integrity verification|checksum.*(?:did not match|mismatch)|invalid document checksum/i
  ).test(internalMessage);
  const routeContractMismatch = error instanceof ApiError
    && (error.status === 404 || error.status === 410)
    && error.code === `HTTP_${error.status}`;
  return {
    message: error instanceof TerminalDocumentViewerError
      ? error.message
      : routeContractMismatch
        ? 'The document service is temporarily unavailable. Try again.'
        : userFacingErrorMessage(error, 'The document could not be opened.'),
    retryable: localCiphertextFailure
      || !(error instanceof TerminalDocumentViewerError || terminalApiFailure || terminalMessage),
    supportCode: viewerSupportCode(error),
  };
}

export default function SecureDocumentScreen() {
  const { id, tripId } = useLocalSearchParams<{ id: string; tripId: string }>();
  const session = useSessionStore((state) => state.session);
  const [uri, setUri] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string | null>(null);
  const [title, setTitle] = useState('Document');
  const [error, setError] = useState<ViewerFailure | null>(null);
  const [opening, setOpening] = useState(true);
  const [rendererLoaded, setRendererLoaded] = useState(false);
  const mounted = useRef(false);
  const attempt = useRef(0);
  const temporaryView = useRef<TemporaryView | null>(null);
  const openInFlight = useRef<OpenOperation | null>(null);
  const suspendedByLifecycle = useRef(false);
  const rendererLoadedRef = useRef(false);
  const automaticRendererRetries = useRef(0);

  const finishTemporaryView = useCallback((discard: boolean) => {
    const temporary = temporaryView.current;
    temporaryView.current = null;
    if (!temporary) return;
    try {
      if (discard) removeTemporaryView(temporary);
      else releaseTemporaryView(temporary);
    } catch {
      // Cleanup is best-effort because a file already removed by the native
      // renderer must not trap the viewer in a second failure.
    }
  }, []);

  const openDocument = useCallback((): Promise<void> => {
    const operationKey = `${session?.sessionId ?? 'anonymous'}:${tripId ?? 'missing'}:${id ?? 'missing'}`;
    const existing = openInFlight.current;
    if (existing?.key === operationKey) return existing.promise;
    existing?.controller.abort();

    const operationAttempt = attempt.current + 1;
    const controller = new AbortController();
    const { signal } = controller;
    attempt.current = operationAttempt;
    finishTemporaryView(false);
    rendererLoadedRef.current = false;
    setRendererLoaded(false);
    setUri(null);
    setError(null);
    setOpening(true);

    let request!: Promise<void>;
    request = (async () => {
      let createdTemporary: TemporaryView | null = null;
      try {
        if (!id || !tripId || !session) {
          throw new TerminalDocumentViewerError('The document could not be opened.');
        }
        const namespace = principalAccountNamespace(session.principal);
        const selectedTripId = session.principal.principalType === 'coordinator'
          ? (() => {
              const selected = useCoordinatorTripStore.getState();
              return selected.accountKey === namespace ? selected.tripId : null;
            })()
          : useSelectedTripStore.getState().tripId;
        if (selectedTripId !== tripId) {
          throw new TerminalDocumentViewerError(
            'Select this trip before opening its offline documents.',
          );
        }
        let document = await getDocument(tripId, id);
        if (!document || document.revoked_at) {
          throw new TerminalDocumentViewerError('This document is no longer available.');
        }
        if (!mounted.current || attempt.current !== operationAttempt) return;
        setTitle(document.display_name);
        setContentType(document.content_type);
        if (
          document.metadata_state !== 'ready' ||
          !document.offline_available ||
          !document.size_bytes ||
          !document.checksum_sha256
        ) {
          // Pending personal metadata is deliberately materialized by the same
          // signed authorization that downloads the first offline copy. Do not
          // dead-end the viewer while the background prefetch is still running.
          await cacheDocument(document, undefined, signal, 'required');
          document = await getDocument(tripId, id);
          if (!document || document.revoked_at) {
            throw new TerminalDocumentViewerError('This document is no longer available.');
          }
        }
        if (
          document.metadata_state !== 'ready' ||
          !document.offline_available ||
          !document.size_bytes ||
          !document.checksum_sha256
        ) {
          throw new Error('This document is still being prepared for offline use.');
        }
        if (!document.offline || document.offlineVersion !== document.version) {
          await cacheDocument(document, undefined, signal, 'required');
        }
        if (!mounted.current || attempt.current !== operationAttempt) return;
        const vaultInput = {
          namespace,
          tripId,
          documentId: document.id,
          version: document.version,
          checksumSha256: document.checksum_sha256,
          expectedSizeBytes: document.size_bytes,
          contentType: document.content_type,
        };
        try {
          createdTemporary = await decryptDocumentForViewing(vaultInput, signal);
        } catch (caught) {
          if (!isLocalOfflineCiphertextError(caught)) throw caught;
          // A post-registration bit flip or truncation is repaired from the signed source. The
          // repository atomically unregisters the damaged copy and leaves a durable retry job if
          // connectivity disappears during this attempt.
          await cacheDocument(document, undefined, signal, 'required');
          createdTemporary = await decryptDocumentForViewing(vaultInput, signal);
        }
        // This timestamp is eviction/LRU bookkeeping, not part of the document
        // authorization or integrity boundary. Do not hold the renderer behind
        // a busy offline database connection after decryption has succeeded.
        void recordOfflineDocumentOpened({
          namespace,
          tripId,
          documentId: document.id,
          version: document.version,
        }).catch(() => undefined);
        if (!mounted.current || attempt.current !== operationAttempt) {
          releaseTemporaryView(createdTemporary);
          createdTemporary = null;
          return;
        }
        temporaryView.current = createdTemporary;
        setUri(createdTemporary.uri);
        createdTemporary = null;
      } catch (caught) {
        if (createdTemporary) {
          try {
            removeTemporaryView(createdTemporary);
          } catch {
            // Preserve the actionable document failure if cleanup also fails.
          }
        }
        if (mounted.current && attempt.current === operationAttempt) {
          setError(viewerFailure(caught));
        }
      } finally {
        if (openInFlight.current?.promise === request) openInFlight.current = null;
        if (mounted.current && attempt.current === operationAttempt) setOpening(false);
      }
    })();
    openInFlight.current = { key: operationKey, promise: request, controller };
    return request;
  }, [finishTemporaryView, id, session, tripId]);

  const handleRendererFailure = useCallback((failedUri: string, message: string) => {
    if (temporaryView.current?.uri !== failedUri) return;
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    finishTemporaryView(true);
    rendererLoadedRef.current = false;
    setRendererLoaded(false);
    setUri(null);
    if (automaticRendererRetries.current < 1 && mounted.current) {
      automaticRendererRetries.current += 1;
      setError(null);
      setOpening(true);
      void openDocument();
      return;
    }
    setOpening(false);
    setError({ message, retryable: true, supportCode: 'DOCUMENT_RENDER_FAILED' });
  }, [finishTemporaryView, openDocument]);

  const markRendererLoaded = useCallback(() => {
    rendererLoadedRef.current = true;
    setRendererLoaded(true);
  }, []);

  const retryDocument = useCallback(() => {
    automaticRendererRetries.current = 0;
    void openDocument();
  }, [openDocument]);

  useEffect(() => {
    mounted.current = true;
    automaticRendererRetries.current = 0;
    void openDocument();
    return () => {
      mounted.current = false;
      attempt.current += 1;
      openInFlight.current?.controller.abort();
      openInFlight.current = null;
      finishTemporaryView(false);
    };
  }, [finishTemporaryView, openDocument]);

  useEffect(() => {
    if (!uri) return;
    const timeout = setTimeout(() => {
      if (!rendererLoadedRef.current) {
        handleRendererFailure(uri, 'The document viewer took too long to display this file.');
      }
    }, 8_000);
    return () => clearTimeout(timeout);
  }, [handleRendererFailure, uri]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        if (suspendedByLifecycle.current) return;
        suspendedByLifecycle.current = true;
        attempt.current += 1;
        openInFlight.current?.controller.abort();
        openInFlight.current = null;
        finishTemporaryView(true);
        rendererLoadedRef.current = false;
        setRendererLoaded(false);
        setUri(null);
        setError(null);
        setOpening(false);
        return;
      }
      if (!suspendedByLifecycle.current || !mounted.current) return;
      suspendedByLifecycle.current = false;
      void openDocument();
    });
    return () => subscription.remove();
  }, [finishTemporaryView, openDocument]);

  const closeDocument = useCallback(() => {
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    finishTemporaryView(false);
    router.back();
  }, [finishTemporaryView]);

  return (
    <Screen scroll={false} contentStyle={styles.screen} bottomInset={8}>
      <View style={styles.header}>
        <Pressable testID="secure-document-close" accessibilityRole="button" accessibilityLabel="Close document" onPress={closeDocument} style={styles.close}>
          <Text style={styles.closeText}>Close</Text>
        </Pressable>
        <Text numberOfLines={1} style={styles.title}>
          {title}
        </Text>
        <View style={styles.headerSpacer} />
      </View>
      {error ? (
        <GlassCard testID="secure-document-error" style={styles.messageCard}>
          <Text accessibilityRole="alert" style={styles.errorTitle}>
            Document unavailable
          </Text>
          <Text style={styles.errorText}>{error.message}</Text>
          <Text testID="secure-document-support-code" style={styles.supportCode}>
            Support code: {error.supportCode}
          </Text>
          {error.retryable ? (
            <PrimaryButton
              label="Retry"
              loading={opening}
              onPress={retryDocument}
            />
          ) : null}
        </GlassCard>
      ) : opening || !uri ? (
        <View testID="secure-document-opening" accessibilityRole="progressbar" accessibilityLabel="Opening document" style={styles.loading}>
          <ActivityIndicator color={colors.greenDeep} size="large" />
          <Text style={styles.loadingText}>Opening your document…</Text>
        </View>
      ) : contentType === 'application/pdf' ? (
        <View
          testID="secure-document-rendered"
          accessible
          accessibilityLabel="Document content"
          accessibilityState={{ busy: !rendererLoaded }}
          style={styles.viewerContainer}
        >
          <Pdf
            key={uri}
            source={{ uri, cache: false }}
            trustAllCerts={false}
            style={styles.viewer}
            enablePaging={false}
            onLoadComplete={markRendererLoaded}
            onError={() => handleRendererFailure(uri, 'The PDF viewer could not render this file.')}
          />
          {!rendererLoaded ? (
            <View pointerEvents="none" style={styles.rendererLoading}>
              <ActivityIndicator color={colors.blueDeep} size="large" />
            </View>
          ) : null}
        </View>
      ) : (
        <View
          testID="secure-document-rendered"
          accessible
          accessibilityLabel="Document content"
          accessibilityState={{ busy: !rendererLoaded }}
          style={styles.viewerContainer}
        >
          <Image
            key={uri}
            source={{ uri }}
            cachePolicy="none"
            contentFit="contain"
            style={styles.viewer}
            accessibilityLabel={title}
            onLoad={markRendererLoaded}
            onError={() => handleRendererFailure(uri, 'The image viewer could not render this file.')}
          />
          {!rendererLoaded ? (
            <View pointerEvents="none" style={styles.rendererLoading}>
              <ActivityIndicator color={colors.blueDeep} size="large" />
            </View>
          ) : null}
        </View>
      )}
      <SensitiveScreenProtection protectionKey="passenger-document-viewer" />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  header: {
    minHeight: 54,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  close: { minWidth: 64, minHeight: 44, justifyContent: 'center' },
  closeText: { color: colors.greenDeep, fontSize: 16, fontWeight: '700' },
  title: { flex: 1, color: colors.ink, textAlign: 'center', fontWeight: '700' },
  headerSpacer: { width: 64 },
  viewerContainer: { flex: 1, backgroundColor: '#EAF0F2' },
  viewer: { flex: 1, backgroundColor: '#EAF0F2' },
  rendererLoading: {
    position: 'absolute',
    inset: 0,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EAF0F2',
  },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.lg },
  loadingText: { color: colors.inkMuted, fontSize: 15 },
  messageCard: { margin: spacing.lg, gap: spacing.sm, borderRadius: radii.md },
  errorTitle: { color: colors.danger, fontSize: 18, fontWeight: '800' },
  errorText: { color: colors.inkMuted, lineHeight: 21 },
  supportCode: { color: colors.inkMuted, fontSize: 12, fontWeight: '700' },
});
