import { Alert, StyleSheet, Text, View } from 'react-native';

import { useSafeSignOut } from '@/core/auth/use-safe-sign-out';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

export function SafeSignOutButton({
  label = 'Sign out',
  testID = 'safe-sign-out',
}: {
  label?: string;
  testID?: string;
}) {
  const signOut = useSafeSignOut();
  const confirmDiscard = () => {
    const count = signOut.blockedActions?.unsynchronized ?? 0;
    Alert.alert(
      'Discard unsynchronized changes?',
      `${count} local ${count === 1 ? 'change has' : 'changes have'} not reached the server. `
        + 'This permanently removes the encrypted local queue and cannot be undone.',
      [
        { text: 'Keep me signed in', style: 'cancel' },
        {
          text: 'Discard and sign out',
          style: 'destructive',
          onPress: () => void signOut.discardAndSignOut(),
        },
      ],
    );
  };
  return (
    <View style={styles.container}>
      {signOut.errorMessage ? (
        <Text accessibilityRole="alert" style={styles.error}>{signOut.errorMessage}</Text>
      ) : null}
      {signOut.blockedActions ? (
        <>
          <PrimaryButton
            testID={`${testID}-synchronize`}
            label="Synchronize, then sign out"
            loading={signOut.isSigningOut}
            tone="secondary"
            onPress={() => void signOut.synchronizeAndSignOut()}
          />
          <PrimaryButton
            testID={`${testID}-discard`}
            label="Discard changes and sign out"
            disabled={signOut.isSigningOut}
            tone="danger"
            onPress={confirmDiscard}
          />
        </>
      ) : (
        <PrimaryButton
          testID={testID}
          label={signOut.errorMessage ? 'Retry secure lock' : label}
          loading={signOut.isSigningOut}
          tone="danger"
          onPress={() => void (signOut.errorMessage ? signOut.retryCleanup() : signOut.signOut())}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.sm },
  error: { color: colors.danger, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
