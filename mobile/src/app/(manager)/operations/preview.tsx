import { Image } from 'expo-image';
import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, Text, View } from 'react-native';
import Pdf from 'react-native-pdf';

import { ApiError } from '@/core/api/client';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import {
  loadManagerDocumentPreview,
  removeManagerDocumentPreview,
  type ManagerPreview,
} from '@/features/manager/data/manager-document-preview';

function first(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

export default function ManagerDocumentPreviewScreen() {
  const params = useLocalSearchParams<{
    tripId?: string | string[];
    passengerId?: string | string[];
    documentType?: string | string[];
    title?: string | string[];
  }>();
  const tripId = first(params.tripId);
  const passengerId = first(params.passengerId);
  const documentTypeValue = first(params.documentType);
  const documentType = documentTypeValue === 'visa' || documentTypeValue === 'flight_ticket'
    ? documentTypeValue
    : null;
  const title = first(params.title) || 'Document preview';
  const [preview, setPreview] = useState<ManagerPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [rendererLoaded, setRendererLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentPreview = useRef<ManagerPreview | null>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const discardPreview = useCallback(() => {
    const current = currentPreview.current;
    currentPreview.current = null;
    setPreview(null);
    if (current) removeManagerDocumentPreview(current);
  }, []);

  const load = useCallback(async () => {
    controller.current?.abort();
    discardPreview();
    setLoading(true);
    setRendererLoaded(false);
    setError(null);
    if (!tripId || !passengerId || !documentType) {
      setLoading(false);
      setError('The requested document preview is invalid.');
      return;
    }
    const operation = new AbortController();
    controller.current = operation;
    try {
      const result = await loadManagerDocumentPreview(
        tripId,
        passengerId,
        documentType,
        operation.signal,
      );
      if (!mounted.current || operation.signal.aborted) {
        removeManagerDocumentPreview(result);
        return;
      }
      currentPreview.current = result;
      setPreview(result);
    } catch (caught) {
      if (!mounted.current || operation.signal.aborted) return;
      setError(caught instanceof ApiError && caught.status === 404
        ? `No ${documentType === 'visa' ? 'visa' : 'flight ticket'} is available for this passenger.`
        : userFacingErrorMessage(caught, 'The document preview could not be loaded.'));
    } finally {
      if (controller.current === operation) controller.current = null;
      if (mounted.current && !operation.signal.aborted) setLoading(false);
    }
  }, [discardPreview, documentType, passengerId, tripId]);

  useEffect(() => {
    mounted.current = true;
    const initialLoad = setTimeout(() => {
      if (mounted.current) void load();
    }, 0);
    return () => {
      clearTimeout(initialLoad);
      mounted.current = false;
      controller.current?.abort();
      controller.current = null;
      const current = currentPreview.current;
      currentPreview.current = null;
      if (current) removeManagerDocumentPreview(current);
    };
  }, [load]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state !== 'active') {
        controller.current?.abort();
        discardPreview();
        setRendererLoaded(false);
        return;
      }
      if (mounted.current && !currentPreview.current) void load();
    });
    return () => subscription.remove();
  }, [discardPreview, load]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <OperationHeader title={title} subtitle="Secure online preview · not stored offline" />
      <View style={styles.viewer}>
        {loading ? <ContentLoading label="Loading document preview" /> : null}
        {error ? <ContentError message={error} onRetry={() => void load()} /> : null}
        {preview ? (
          <View testID="manager-document-preview-rendered" style={styles.document}>
            {preview.contentType === 'application/pdf' ? (
              <Pdf
                source={{ uri: preview.file.uri, cache: false }}
                trustAllCerts={false}
                onLoadComplete={() => setRendererLoaded(true)}
                onError={() => setError('The PDF viewer could not display this document.')}
                style={styles.document}
              />
            ) : (
              <Image
                source={{ uri: preview.file.uri }}
                cachePolicy="none"
                contentFit="contain"
                onLoad={() => setRendererLoaded(true)}
                onError={() => setError('The image viewer could not display this document.')}
                style={styles.document}
              />
            )}
          </View>
        ) : null}
        {preview && !rendererLoaded && !error ? (
          <View pointerEvents="none" style={styles.rendererLoading}>
            <ContentLoading label="Opening preview" />
          </View>
        ) : null}
      </View>
      <Text style={styles.notice}>This preview is removed from the device when you leave this page.</Text>
      <SensitiveScreenProtection protectionKey="manager-document-preview" />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.md },
  viewer: { flex: 1, minHeight: 420 },
  document: { flex: 1, width: '100%', backgroundColor: 'transparent' },
  rendererLoading: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center' },
  notice: { color: colors.inkMuted, fontSize: 11, lineHeight: 16, textAlign: 'center' },
});
