import Camera from 'lucide-react-native/icons/camera';
import Check from 'lucide-react-native/icons/check';
import CircleCheckBig from 'lucide-react-native/icons/circle-check-big';
import Lightbulb from 'lucide-react-native/icons/lightbulb';
import ScanFace from 'lucide-react-native/icons/scan-face';
import ShieldCheck from 'lucide-react-native/icons/shield-check';
import TriangleAlert from 'lucide-react-native/icons/triangle-alert';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';

import type { MyPhotosSummary } from '../api/contracts';
import type { FaceScanState } from '../model/face-scan-machine';
import {
  faceScanFailureBodyCopy,
  faceScanFailureCopy,
} from './face-scan-failure-copy';

type Props = Readonly<{
  state: FaceScanState;
  summary: MyPhotosSummary;
  busy: boolean;
  onContinue: () => void;
  onAcceptConsent: () => void;
  onChallengeMode: (mode: 'movement_and_light' | 'movement_only') => void;
  onAllowCamera: () => void;
  onOpenSettings: () => void;
  onStart: () => void;
  onRetry: () => void;
  onDone: () => void;
}>;

function Instruction({ children }: Readonly<{ children: string }>) {
  return (
    <View style={styles.instruction}>
      <Check color={colors.greenDeep} size={19} strokeWidth={3} />
      <Text style={styles.instructionText}>{children}</Text>
    </View>
  );
}

function ConsentSection({ title, body }: Readonly<{ title: string; body: string }>) {
  return (
    <View style={styles.consentSection}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.body}>{body}</Text>
    </View>
  );
}

export function FaceScanStepContent({
  state,
  summary,
  busy,
  onContinue,
  onAcceptConsent,
  onChallengeMode,
  onAllowCamera,
  onOpenSettings,
  onStart,
  onRetry,
  onDone,
}: Props) {
  const messages = useMessages();
  if (state.step === 'explanation') {
    return (
      <GlassCard style={styles.card}>
        <ScanFace color={colors.greenDeep} size={42} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosFindEveryPhoto()}</Text>
        <Text style={styles.body}>{messages.myPhotosPurposeExplanation()}</Text>
        <Text style={styles.notice}>{messages.myPhotosAccuracyNotice()}</Text>
        <PrimaryButton label={messages.myPhotosContinue()} onPress={onContinue} />
      </GlassCard>
    );
  }
  if (state.step === 'consent') {
    return (
      <GlassCard style={styles.card}>
        <ShieldCheck color={colors.greenDeep} size={38} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosConsentTitle()}</Text>
        <ConsentSection title={messages.myPhotosConsentPurpose()} body={summary.consent.purpose} />
        <ConsentSection title={messages.myPhotosConsentDataUsed()} body={summary.consent.biometric_data_used} />
        <ConsentSection title={messages.myPhotosConsentRetention()} body={summary.consent.retention} />
        <ConsentSection title={messages.myPhotosConsentProvider()} body={summary.consent.provider_processing} />
        <ConsentSection title={messages.myPhotosConsentDeletion()} body={summary.consent.deletion} />
        <PrimaryButton label={messages.myPhotosConsentAccept()} loading={busy} onPress={onAcceptConsent} />
      </GlassCard>
    );
  }
  if (state.step === 'preparation') {
    const movementOnly = state.challengeMode === 'movement_only';
    return (
      <GlassCard style={styles.card}>
        <Camera color={colors.greenDeep} size={38} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosPreparationTitle()}</Text>
        <Instruction>{messages.myPhotosOnlyPerson()}</Instruction>
        <Instruction>{messages.myPhotosEvenLighting()}</Instruction>
        <Instruction>{messages.myPhotosEyeLevel()}</Instruction>
        <Instruction>{messages.myPhotosRemoveCoverings()}</Instruction>
        <View style={styles.warning}>
          <Lightbulb color={colors.warning} size={21} />
          <Text style={styles.warningText}>{messages.myPhotosPhotosensitivityWarning()}</Text>
        </View>
        <View accessibilityRole="radiogroup" style={styles.modeGroup}>
          <Pressable
            accessibilityRole="radio"
            accessibilityState={{ checked: !movementOnly }}
            onPress={() => onChallengeMode('movement_and_light')}
            style={[styles.mode, !movementOnly && styles.modeSelected]}>
            <Text style={[styles.modeText, !movementOnly && styles.modeTextSelected]}>{messages.myPhotosUseMovementAndLight()}</Text>
          </Pressable>
          <Pressable
            accessibilityRole="radio"
            accessibilityState={{ checked: movementOnly }}
            onPress={() => onChallengeMode('movement_only')}
            style={[styles.mode, movementOnly && styles.modeSelected]}>
            <Text style={[styles.modeText, movementOnly && styles.modeTextSelected]}>{messages.myPhotosUseMovementOnly()}</Text>
          </Pressable>
        </View>
        <PrimaryButton label={messages.myPhotosContinue()} onPress={onContinue} />
      </GlassCard>
    );
  }
  if (state.step === 'camera_permission') {
    return (
      <GlassCard style={styles.card}>
        <Camera color={colors.greenDeep} size={38} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosCameraPermissionTitle()}</Text>
        <Text style={styles.body}>{messages.myPhotosCameraPermissionMessage()}</Text>
        <PrimaryButton label={messages.myPhotosAllowCamera()} loading={busy} onPress={onAllowCamera} />
      </GlassCard>
    );
  }
  if (state.step === 'ready') {
    return (
      <GlassCard style={styles.card}>
        <ScanFace color={colors.greenDeep} size={42} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosReadyTitle()}</Text>
        <Text style={styles.body}>{messages.myPhotosReadyMessage()}</Text>
        {summary.capability.client_flow === 'development_simulator' ? (
          <Text style={styles.developmentNotice}>{messages.myPhotosDevelopmentSimulation()}</Text>
        ) : null}
        <PrimaryButton label={messages.myPhotosStartScan()} loading={busy} onPress={onStart} />
      </GlassCard>
    );
  }
  if (state.step === 'starting' || state.step === 'processing') {
    return (
      <GlassCard accessibilityLiveRegion="polite" style={styles.centerCard}>
        <ActivityIndicator accessibilityLabel={messages.loading()} color={colors.greenDeep} size="large" />
        <Text accessibilityRole="header" style={styles.title}>
          {state.step === 'processing' ? messages.myPhotosSecureProcessing() : messages.myPhotosScanRunning()}
        </Text>
        <Text style={styles.body}>
          {state.step === 'processing'
            ? messages.myPhotosSecureProcessingMessage()
            : messages.myPhotosRetryNewSession()}
        </Text>
      </GlassCard>
    );
  }
  if (state.step === 'success') {
    return (
      <GlassCard accessibilityLiveRegion="polite" style={styles.centerCard}>
        <CircleCheckBig color={colors.greenDeep} size={50} />
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosScanSuccess()}</Text>
        <Text style={styles.body}>{messages.myPhotosScanSuccessMessage()}</Text>
        <PrimaryButton label={messages.myPhotosClose()} onPress={onDone} />
      </GlassCard>
    );
  }
  if (state.step === 'failure') {
    const blocked = state.reason === 'camera_blocked';
    return (
      <GlassCard accessibilityLiveRegion="assertive" style={[styles.card, styles.failureCard]}>
        <TriangleAlert color={colors.danger} size={42} />
        <Text accessibilityRole="header" style={styles.title}>{faceScanFailureCopy(state.reason, messages)}</Text>
        <Text style={styles.body}>
          {state.retryAfterSeconds
            ? messages.myPhotosCooldownRemaining(state.retryAfterSeconds)
            : state.pendingCompletion
              ? messages.myPhotosSecureProcessingMessage()
              : faceScanFailureBodyCopy(state.reason, messages)}
        </Text>
        {blocked ? (
          <PrimaryButton label={messages.myPhotosOpenSettings()} tone="secondary" onPress={onOpenSettings} />
        ) : state.retryable && !state.retryAfterSeconds ? (
          <PrimaryButton label={messages.myPhotosRetry()} onPress={onRetry} />
        ) : null}
      </GlassCard>
    );
  }
  return null;
}

const styles = StyleSheet.create({
  card: { gap: spacing.lg },
  centerCard: { gap: spacing.lg, alignItems: 'center', textAlign: 'center' },
  failureCard: { borderColor: 'rgba(184,64,77,0.3)', backgroundColor: 'rgba(255,242,243,0.94)' },
  title: { color: colors.ink, fontSize: 24, lineHeight: 30, fontWeight: '900' },
  body: { color: colors.inkMuted, fontSize: 15, lineHeight: 23 },
  notice: { color: colors.blueDeep, fontSize: 13, lineHeight: 20, fontWeight: '700' },
  developmentNotice: { color: colors.warning, fontSize: 13, lineHeight: 20, fontWeight: '800' },
  instruction: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  instructionText: { flex: 1, color: colors.ink, fontSize: 15, lineHeight: 22 },
  consentSection: { gap: spacing.xs },
  sectionTitle: { color: colors.ink, fontSize: 14, fontWeight: '900' },
  warning: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, borderRadius: radii.md, backgroundColor: '#FFF8ED', padding: spacing.md },
  warningText: { flex: 1, color: colors.warning, fontSize: 13, lineHeight: 20, fontWeight: '700' },
  modeGroup: { gap: spacing.sm },
  mode: { minHeight: 48, justifyContent: 'center', borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.md, backgroundColor: colors.surfaceStrong },
  modeSelected: { borderColor: colors.greenDeep, backgroundColor: colors.greenSoft },
  modeText: { color: colors.inkMuted, fontSize: 14, fontWeight: '800' },
  modeTextSelected: { color: colors.greenDeep },
});
