import Eraser from 'lucide-react-native/icons/eraser';
import ScanFace from 'lucide-react-native/icons/scan-face';
import ShieldX from 'lucide-react-native/icons/shield-x';
import Trash2 from 'lucide-react-native/icons/trash-2';
import type { ReactNode } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';

type Props = Readonly<{
  busy: boolean;
  serverActionsAvailable: boolean;
  onRemoveDownloads: () => void;
  onClearStorage: () => void;
  onDeleteEnrollment: (scope: 'enrollment_only' | 'enrollment_and_search_data') => void;
}>;

function ManagementAction({
  icon,
  title,
  message,
  danger = false,
  disabled,
  onPress,
}: Readonly<{
  icon: ReactNode;
  title: string;
  message: string;
  danger?: boolean;
  disabled: boolean;
  onPress: () => void;
}>) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${message}`}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.action, pressed && styles.pressed, disabled && styles.disabled]}>
      <View style={[styles.actionIcon, danger && styles.dangerIcon]}>{icon}</View>
      <View style={styles.copy}>
        <Text style={[styles.actionTitle, danger && styles.dangerText]}>{title}</Text>
        <Text style={styles.actionMessage}>{message}</Text>
      </View>
    </Pressable>
  );
}

export function MyPhotosManagementCard({
  busy,
  serverActionsAvailable,
  onClearStorage,
  onRemoveDownloads,
  onDeleteEnrollment,
}: Props) {
  const messages = useMessages();
  const confirm = (
    title: string,
    message: string,
    action: () => void,
  ) => Alert.alert(title, message, [
    { text: messages.myPhotosKeepData(), style: 'cancel' },
    { text: messages.myPhotosConfirmRemove(), style: 'destructive', onPress: action },
  ]);
  return (
    <GlassCard style={styles.card}>
      <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosStorageAndPrivacy()}</Text>
      <Text style={styles.explanation}>{messages.myPhotosStorageExplanation()}</Text>
      {!serverActionsAvailable ? (
        <Text accessibilityRole="alert" style={styles.serverUnavailable}>
          {messages.myPhotosRecoverableError()}
        </Text>
      ) : null}
      <ManagementAction
        disabled={busy}
        icon={<Eraser color={colors.blueDeep} size={22} />}
        message={messages.myPhotosRemoveDownloadsWarning()}
        onPress={() => confirm(messages.myPhotosRemoveDownloads(), messages.myPhotosRemoveDownloadsWarning(), onRemoveDownloads)}
        title={messages.myPhotosRemoveDownloads()}
      />
      <ManagementAction
        danger
        disabled={busy}
        icon={<Trash2 color={colors.danger} size={22} />}
        message={messages.myPhotosClearStorageWarning()}
        onPress={() => confirm(
          messages.myPhotosClearStorage(),
          messages.myPhotosClearStorageWarning(),
          onClearStorage,
        )}
        title={messages.myPhotosClearStorage()}
      />
      <ManagementAction
        danger
        disabled={busy || !serverActionsAvailable}
        icon={<ScanFace color={colors.danger} size={22} />}
        message={messages.myPhotosDeleteFaceScanWarning()}
        onPress={() => confirm(
          messages.myPhotosDeleteFaceScan(),
          messages.myPhotosDeleteFaceScanWarning(),
          () => onDeleteEnrollment('enrollment_only'),
        )}
        title={messages.myPhotosDeleteFaceScan()}
      />
      <ManagementAction
        danger
        disabled={busy || !serverActionsAvailable}
        icon={<ShieldX color={colors.danger} size={22} />}
        message={messages.myPhotosRemoveSearchDataWarning()}
        onPress={() => confirm(
          messages.myPhotosRemoveSearchData(),
          messages.myPhotosRemoveSearchDataWarning(),
          () => onDeleteEnrollment('enrollment_and_search_data'),
        )}
        title={messages.myPhotosRemoveSearchData()}
      />
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  title: { color: colors.ink, fontSize: 21, fontWeight: '900' },
  explanation: { color: colors.inkMuted, fontSize: 13, lineHeight: 20 },
  serverUnavailable: { color: colors.warning, fontSize: 13, lineHeight: 20, fontWeight: '800' },
  action: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, backgroundColor: colors.surfaceStrong },
  actionIcon: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.blueSoft },
  dangerIcon: { backgroundColor: '#FFF0F2' },
  copy: { flex: 1, gap: 3 },
  actionTitle: { color: colors.ink, fontSize: 15, fontWeight: '900' },
  dangerText: { color: colors.danger },
  actionMessage: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  pressed: { opacity: 0.72 },
  disabled: { opacity: 0.55 },
});
