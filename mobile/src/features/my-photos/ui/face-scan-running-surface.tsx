import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

import type { FaceScanClientFlow } from '../model/face-scan-machine';
import { FaceScanCamera } from './face-scan-camera';

type Props = Readonly<{
  clientFlow: FaceScanClientFlow;
  onCancel: () => void;
  onCameraUnavailable: () => void;
  onCompleteDevelopmentSimulation: () => void;
}>;

/** Camera ownership is exclusive: JavaScript renders CameraView only for the
 * explicitly development-only guidance simulator. The production native
 * provider component owns camera capture and streams no frames through JS. */
export function FaceScanRunningSurface({
  clientFlow,
  onCancel,
  onCameraUnavailable,
  onCompleteDevelopmentSimulation,
}: Props) {
  const messages = useMessages();
  if (clientFlow === 'development_simulator') {
    return (
      <FaceScanCamera
        developmentSimulation
        onCameraUnavailable={onCameraUnavailable}
        onCancel={onCancel}
        onCompleteDevelopmentSimulation={onCompleteDevelopmentSimulation}
      />
    );
  }
  return (
    <View style={styles.nativeHost} testID="face-scan-native-host">
      <ActivityIndicator accessibilityLabel={messages.loading()} color={colors.green} size="large" />
      <Text accessibilityRole="header" style={styles.nativeTitle}>{messages.myPhotosScanRunning()}</Text>
      <Text style={styles.nativeBody}>{messages.myPhotosNativeScanBoundary()}</Text>
      <View style={styles.cancelAction}>
        <PrimaryButton label={messages.myPhotosCancel()} tone="secondary" onPress={onCancel} />
      </View>
      <SensitiveScreenProtection protectionKey="my-photos-native-face-scan-host" />
    </View>
  );
}

const styles = StyleSheet.create({
  nativeHost: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.lg,
    backgroundColor: colors.navy,
    padding: spacing.xl,
  },
  nativeTitle: { color: colors.white, fontSize: 24, lineHeight: 30, fontWeight: '900', textAlign: 'center' },
  nativeBody: { maxWidth: 420, color: colors.white, fontSize: 14, lineHeight: 22, fontWeight: '700', textAlign: 'center' },
  cancelAction: { alignSelf: 'stretch', marginTop: spacing.md },
});
