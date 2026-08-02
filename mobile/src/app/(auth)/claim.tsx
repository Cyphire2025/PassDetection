import { Redirect, router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { activateSession } from '@/core/auth/session-service';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import { verifyPassengerClaim } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function ClaimScreen() {
  const flow = useAuthFlowStore();
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(
    flow.claims.length === 1 ? (flow.claims[0]?.claim_id ?? null) : null,
  );
  const [verificationValue, setVerificationValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(
    () => flow.claims.find((claim) => claim.claim_id === selectedClaimId),
    [flow.claims, selectedClaimId],
  );

  if (!flow.challengeId) return <Redirect href="/(auth)/phone" />;
  const needsSecondary = flow.claims.length === 0 || selected?.requires_secondary_verification;

  async function submit() {
    if (flow.claims.length > 0 && !selectedClaimId) {
      setError('Select the trip you want to open.');
      return;
    }
    if (needsSecondary && verificationValue.trim().length < 2) {
      setError('Enter the additional detail requested by your travel team.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await verifyPassengerClaim({
        challengeId: flow.challengeId!,
        ...(selectedClaimId ? { claimId: selectedClaimId } : {}),
        ...(verificationValue.trim() ? { verificationValue: verificationValue.trim() } : {}),
      });
      if (result.status === 'authenticated' && result.tokens) {
        await activateSession(result.tokens);
        flow.reset();
        router.replace('/');
        return;
      }
      flow.setClaims(result.claims);
      setError('That information could not be verified. Check it and try again.');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Trip identity"
      title={flow.claims.length ? 'Choose your trip.' : 'One more detail.'}
      description={
        flow.claims.length
          ? 'Only currently eligible trips are shown. Your selection is verified again by the server.'
          : 'Shared or duplicate phone numbers need an additional detail supplied by your travel team.'
      }>
      {flow.claims.map((claim) => {
        const selectedRow = selectedClaimId === claim.claim_id;
        return (
          <Pressable
            accessibilityRole="radio"
            accessibilityState={{ selected: selectedRow }}
            key={claim.claim_id}
            onPress={() => setSelectedClaimId(claim.claim_id)}>
            <GlassCard style={[styles.claim, selectedRow && styles.selectedClaim]}>
              <View style={styles.claimText}>
                <Text style={styles.claimTitle}>{claim.group_name}</Text>
                <Text style={styles.claimMeta}>
                  {[claim.destination, claim.travel_date].filter(Boolean).join(' · ') || 'Trip details available after verification'}
                </Text>
              </View>
              <View style={[styles.radio, selectedRow && styles.radioSelected]} />
            </GlassCard>
          </Pressable>
        );
      })}
      {needsSecondary ? (
        <TextField
          label="Passenger, employee or booking detail"
          placeholder="Enter the detail provided to you"
          autoCapitalize="characters"
          value={verificationValue}
          onChangeText={setVerificationValue}
          maxLength={128}
        />
      ) : null}
      <AuthError message={error} />
      <PrimaryButton label="Open my trip" loading={loading} onPress={() => void submit()} />
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  claim: { borderRadius: radii.md, flexDirection: 'row', alignItems: 'center', padding: spacing.md },
  selectedClaim: { borderColor: colors.green, borderWidth: 2 },
  claimText: { flex: 1, gap: spacing.xs },
  claimTitle: { color: colors.ink, fontSize: 16, fontWeight: '700' },
  claimMeta: { color: colors.inkMuted, fontSize: 13 },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: colors.border },
  radioSelected: { borderColor: colors.greenDeep, backgroundColor: colors.green },
});
