import * as SplashScreen from 'expo-splash-screen';
import * as Updates from 'expo-updates';
import React, { Component, Fragment, type ErrorInfo, type PropsWithChildren } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { requestSafeSignOut } from '@/core/auth/use-safe-sign-out';
import { useSessionStore } from '@/core/auth/session-store';
import { colors, radii, spacing } from '@/design/theme';

import { recordApplicationDiagnostic } from './application-diagnostics';

const MAX_INLINE_RECOVERIES = 2;
const SAFE_RECOVERY_FAILURE = 'The app could not finish that recovery step. Restart and try again.';

type State = {
  hasError: boolean;
  recoveryAttempts: number;
  resetVersion: number;
  pendingAction: 'sign-out' | 'restart' | null;
  actionError: string | null;
};

const INITIAL_STATE: State = {
  hasError: false,
  recoveryAttempts: 0,
  resetVersion: 0,
  pendingAction: null,
  actionError: null,
};

export class ApplicationErrorBoundary extends Component<PropsWithChildren, State> {
  override state: State = INITIAL_STATE;

  static getDerivedStateFromError(): Partial<State> {
    // Never retain the thrown value: native messages and stacks may contain
    // storage paths, SQL, provider diagnostics, or personal information.
    return { hasError: true, pendingAction: null };
  }

  override componentDidCatch(_error: unknown, _info: ErrorInfo): void {
    recordApplicationDiagnostic('APP_RENDER_FAILED', this.state.recoveryAttempts);
    // Startup failures may occur before AppProviders gets a chance to dismiss
    // the native splash screen. Ensure the privacy-safe recovery UI is visible.
    void SplashScreen.hideAsync().catch(() => undefined);
  }

  private retry = (): void => {
    if (this.state.recoveryAttempts >= MAX_INLINE_RECOVERIES) return;
    recordApplicationDiagnostic('APP_RECOVERY_REQUESTED', this.state.recoveryAttempts + 1);
    this.setState((current) => ({
      hasError: false,
      recoveryAttempts: current.recoveryAttempts + 1,
      resetVersion: current.resetVersion + 1,
      pendingAction: null,
      actionError: null,
    }));
  };

  private signOut = async (): Promise<void> => {
    if (this.state.pendingAction) return;
    recordApplicationDiagnostic('APP_SIGN_OUT_REQUESTED', this.state.recoveryAttempts);
    this.setState({ pendingAction: 'sign-out', actionError: null });
    let completed = false;
    try {
      const result = await requestSafeSignOut();
      completed = result.ok;
    } catch {
      // The error value is deliberately ignored and never retained or logged.
    }
    if (!completed) {
      recordApplicationDiagnostic('APP_RECOVERY_ACTION_FAILED', this.state.recoveryAttempts);
      this.setState({ pendingAction: null, actionError: SAFE_RECOVERY_FAILURE });
      return;
    }
    this.setState((current) => ({
      ...INITIAL_STATE,
      resetVersion: current.resetVersion + 1,
    }));
  };

  private restart = async (): Promise<void> => {
    if (this.state.pendingAction) return;
    recordApplicationDiagnostic('APP_RESTART_REQUESTED', this.state.recoveryAttempts);
    this.setState({ pendingAction: 'restart', actionError: null });
    try {
      await Updates.reloadAsync();
    } catch {
      recordApplicationDiagnostic('APP_RECOVERY_ACTION_FAILED', this.state.recoveryAttempts);
      this.setState({ pendingAction: null, actionError: SAFE_RECOVERY_FAILURE });
    }
  };

  override render() {
    if (!this.state.hasError) {
      return <Fragment key={this.state.resetVersion}>{this.props.children}</Fragment>;
    }

    const canRetry = this.state.recoveryAttempts < MAX_INLINE_RECOVERIES;
    const canSignOut = useSessionStore.getState().status === 'authenticated';
    const busy = this.state.pendingAction !== null;

    return (
      <SafeAreaView edges={['top', 'right', 'bottom', 'left']} style={styles.safeArea}>
        <View style={styles.content}>
          <View accessibilityElementsHidden style={styles.symbol}>
            <Text style={styles.symbolText}>!</Text>
          </View>
          <Text accessibilityRole="header" style={styles.title}>Something interrupted the app.</Text>
          <Text style={styles.message}>
            Your private trip data remains protected. Try restoring this screen or restart the app.
          </Text>
          {this.state.actionError ? (
            <Text accessibilityRole="alert" style={styles.error}>{this.state.actionError}</Text>
          ) : null}
          <View style={styles.actions}>
            {canRetry ? (
              <RecoveryButton disabled={busy} label="Try again" onPress={this.retry} primary />
            ) : null}
            {canSignOut ? (
              <RecoveryButton disabled={busy} label="Sign out safely" onPress={() => void this.signOut()} />
            ) : null}
            <RecoveryButton disabled={busy} label="Restart app" onPress={() => void this.restart()} />
          </View>
          {busy ? <ActivityIndicator accessibilityLabel="Recovering app" color={colors.greenDeep} /> : null}
        </View>
      </SafeAreaView>
    );
  }
}

function RecoveryButton({
  disabled,
  label,
  onPress,
  primary = false,
}: {
  disabled: boolean;
  label: string;
  onPress: () => void;
  primary?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        primary ? styles.primaryButton : styles.secondaryButton,
        (pressed || disabled) && styles.buttonMuted,
      ]}>
      <Text style={primary ? styles.primaryLabel : styles.secondaryLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.greenWash },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
  },
  symbol: {
    width: 64,
    height: 64,
    borderRadius: radii.lg,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
    borderWidth: 1,
    borderColor: colors.border,
  },
  symbolText: { color: colors.greenDeep, fontSize: 32, fontWeight: '900' },
  title: { color: colors.ink, fontSize: 25, lineHeight: 31, fontWeight: '900', textAlign: 'center' },
  message: { color: colors.inkMuted, fontSize: 16, lineHeight: 23, textAlign: 'center', maxWidth: 420 },
  error: { color: colors.danger, fontSize: 14, lineHeight: 20, textAlign: 'center', maxWidth: 420 },
  actions: { width: '100%', maxWidth: 360, gap: spacing.sm },
  button: {
    minHeight: 48,
    borderRadius: radii.pill,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  primaryButton: { backgroundColor: colors.green },
  secondaryButton: { backgroundColor: colors.surfaceStrong, borderWidth: 1, borderColor: colors.border },
  buttonMuted: { opacity: 0.62 },
  primaryLabel: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  secondaryLabel: { color: colors.greenDeep, fontSize: 16, fontWeight: '800' },
});
