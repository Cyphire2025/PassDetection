import { CameraView } from 'expo-camera';
import X from 'lucide-react-native/icons/x';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';

type Props = Readonly<{
  developmentSimulation: boolean;
  onCancel: () => void;
  onCameraUnavailable: () => void;
  onCompleteDevelopmentSimulation: () => void;
}>;

export function FaceScanCamera({
  developmentSimulation,
  onCancel,
  onCameraUnavailable,
  onCompleteDevelopmentSimulation,
}: Props) {
  const messages = useMessages();
  return (
    <View style={styles.root}>
      <CameraView
        accessibilityElementsHidden
        active
        facing="front"
        mirror
        onMountError={onCameraUnavailable}
        style={StyleSheet.absoluteFill}
      />
      <View pointerEvents="none" style={styles.shade} />
      <View pointerEvents="none" style={styles.oval} />
      <View accessibilityLiveRegion="polite" style={styles.guidance}>
        <Text style={styles.eyebrow}>{messages.myPhotosGuidanceOnly()}</Text>
        <Text accessibilityRole="header" style={styles.guidanceText}>{messages.myPhotosScanGuidance()}</Text>
        {developmentSimulation ? (
          <Text style={styles.simulation}>{messages.myPhotosDevelopmentSimulation()}</Text>
        ) : null}
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={messages.myPhotosCancel()}
        onPress={onCancel}
        style={styles.cancel}>
        <X color={colors.white} size={24} />
      </Pressable>
      {developmentSimulation ? (
        <View style={styles.developmentControl}>
          <PrimaryButton
            label={messages.myPhotosCompleteSimulation()}
            onPress={onCompleteDevelopmentSimulation}
          />
        </View>
      ) : null}
      <SensitiveScreenProtection protectionKey="my-photos-face-scan" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, overflow: 'hidden', backgroundColor: colors.navy },
  shade: { position: 'absolute', inset: 0, backgroundColor: 'rgba(8,41,54,0.28)' },
  oval: { position: 'absolute', width: '72%', aspectRatio: 0.76, alignSelf: 'center', top: '18%', borderWidth: 4, borderColor: colors.white, borderRadius: 999, shadowColor: colors.navy, shadowOpacity: 0.75, shadowRadius: 9, shadowOffset: { width: 0, height: 2 } },
  guidance: { position: 'absolute', left: spacing.lg, right: spacing.lg, top: spacing.xxl, alignItems: 'center', gap: spacing.xs, borderRadius: radii.md, backgroundColor: 'rgba(8,41,54,0.78)', padding: spacing.md },
  eyebrow: { color: colors.green, fontSize: 11, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.8 },
  guidanceText: { color: colors.white, fontSize: 18, fontWeight: '900', textAlign: 'center' },
  simulation: { color: colors.white, fontSize: 12, lineHeight: 17, fontWeight: '700', textAlign: 'center' },
  cancel: { position: 'absolute', right: spacing.lg, top: spacing.xxl, width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(8,41,54,0.88)', alignItems: 'center', justifyContent: 'center' },
  developmentControl: { position: 'absolute', left: spacing.lg, right: spacing.lg, bottom: spacing.xxl },
});
