import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import * as ScreenCapture from 'expo-screen-capture';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import Pdf from 'react-native-pdf';

import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { decryptDocumentForViewing, removeTemporaryView } from '@/core/storage/vault';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { cacheDocument, getDocument } from '@/features/content/data/content-repository';

export default function SecureDocumentScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const session = useSessionStore((state) => state.session);
  const [uri, setUri] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string | null>(null);
  const [title, setTitle] = useState('Secure document');
  const [error, setError] = useState<string | null>(null);

  ScreenCapture.usePreventScreenCapture(`document-${id ?? 'unknown'}`);

  useEffect(() => {
    let temporary: Awaited<ReturnType<typeof decryptDocumentForViewing>> | null = null;
    let active = true;
    void (async () => {
      try {
        if (!id || !session) throw new Error('The document could not be opened.');
        const document = await getDocument(id);
        if (!document) throw new Error('This document is no longer available.');
        if (
          document.metadata_state !== 'ready' ||
          !document.offline_available ||
          !document.size_bytes ||
          !document.checksum_sha256
        ) {
          throw new Error('This document is still being prepared for secure offline access.');
        }
        setTitle(document.display_name);
        setContentType(document.content_type);
        if (!document.offline || document.offlineVersion !== document.version) {
          await cacheDocument(document);
        }
        const namespace = accountNamespace({
          agencyId: session.principal.agencyId,
          principalId: session.principal.id,
        });
        temporary = await decryptDocumentForViewing({
          namespace,
          tripId: document.trip_id,
          documentId: document.id,
          version: document.version,
          checksumSha256: document.checksum_sha256,
          expectedSizeBytes: document.size_bytes,
          contentType: document.content_type,
        });
        if (active) setUri(temporary.uri);
        else removeTemporaryView(temporary);
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : 'The document could not be opened.');
        }
      }
    })();
    return () => {
      active = false;
      if (temporary) removeTemporaryView(temporary);
    };
  }, [id, session]);

  return (
    <Screen scroll={false} contentStyle={styles.screen} bottomInset={8}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close document" onPress={() => router.back()} style={styles.close}>
          <Text style={styles.closeText}>Close</Text>
        </Pressable>
        <Text numberOfLines={1} style={styles.title}>
          {title}
        </Text>
        <View style={styles.headerSpacer} />
      </View>
      {error ? (
        <GlassCard style={styles.messageCard}>
          <Text accessibilityRole="alert" style={styles.errorTitle}>
            Document unavailable
          </Text>
          <Text style={styles.errorText}>{error}</Text>
        </GlassCard>
      ) : !uri ? (
        <View accessibilityRole="progressbar" accessibilityLabel="Opening encrypted document" style={styles.loading}>
          <ActivityIndicator color={colors.greenDeep} size="large" />
          <Text style={styles.loadingText}>Verifying and opening the encrypted copy…</Text>
        </View>
      ) : contentType === 'application/pdf' ? (
        <Pdf
          source={{ uri, cache: false }}
          trustAllCerts={false}
          style={styles.viewer}
          enablePaging={false}
          onError={() => setError('The PDF viewer could not render this file.')}
        />
      ) : (
        <Image source={{ uri }} contentFit="contain" style={styles.viewer} accessibilityLabel={title} />
      )}
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
  viewer: { flex: 1, backgroundColor: '#EAF0F2' },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.lg },
  loadingText: { color: colors.inkMuted, fontSize: 15 },
  messageCard: { margin: spacing.lg, gap: spacing.sm, borderRadius: radii.md },
  errorTitle: { color: colors.danger, fontSize: 18, fontWeight: '800' },
  errorText: { color: colors.inkMuted, lineHeight: 21 },
});
