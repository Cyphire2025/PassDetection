import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import { drainIncidentQueue, enqueueIncident, incidentQueueCount, type IncidentInput } from '@/features/coordinator/data/operations-repository';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function CoordinatorIncidentsScreen() {
  const trips = useTrips();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState<IncidentInput['severity']>('medium');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit() {
    if (!trips.selectedTripId) return;
    setSaving(true);
    setMessage(null);
    try {
      await enqueueIncident(trips.selectedTripId, { title, description, severity });
      await drainIncidentQueue(trips.selectedTripId).catch(() => undefined);
      const pending = await incidentQueueCount(trips.selectedTripId);
      setMessage(pending ? 'Incident saved securely and waiting to synchronize.' : 'Incident reported successfully.');
      setTitle('');
      setDescription('');
    } catch {
      setMessage('The incident could not be saved. Check the fields and try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen contentStyle={styles.screen} scrollProps={{ keyboardShouldPersistTaps: 'handled' }}>
      <OperationHeader title="Report incident" subtitle={trips.selectedTrip?.name || 'Selected trip'} />
      <GlassCard style={styles.form}>
        <TextField label="Short title" value={title} onChangeText={setTitle} maxLength={160} placeholder="What happened?" />
        <TextField label="Details" value={description} onChangeText={setDescription} maxLength={2000} multiline numberOfLines={5} textAlignVertical="top" placeholder="Record operational facts only. Do not include passport data." />
        <Text style={styles.label}>Severity</Text>
        <View style={styles.severityRow}>
          {(['low', 'medium', 'high', 'critical'] as const).map((value) => (
            <Pressable key={value} accessibilityRole="radio" accessibilityState={{ selected: severity === value }} onPress={() => setSeverity(value)} style={[styles.chip, severity === value && styles.selectedChip]}>
              <Text style={[styles.chipText, severity === value && styles.selectedChipText]}>{value}</Text>
            </Pressable>
          ))}
        </View>
        <PrimaryButton label="Save incident report" loading={saving} disabled={title.trim().length < 3 || description.trim().length < 3} onPress={() => void submit()} />
        {message ? <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text> : null}
      </GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  form: { gap: spacing.lg, borderRadius: radii.md },
  label: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  severityRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: { minHeight: 42, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: radii.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceStrong },
  selectedChip: { backgroundColor: colors.greenSoft, borderColor: colors.green },
  chipText: { color: colors.inkMuted, fontWeight: '700', textTransform: 'capitalize' },
  selectedChipText: { color: colors.greenDeep },
  message: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
