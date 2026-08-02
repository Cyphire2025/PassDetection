import Bell from 'lucide-react-native/icons/bell';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import FileWarning from 'lucide-react-native/icons/file-exclamation-point';
import FileText from 'lucide-react-native/icons/file-text';
import UserRound from 'lucide-react-native/icons/user-round';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

const operations = [
  { route: '/(coordinator)/operations/common-documents' as const, label: 'Common Documents', description: 'Published itinerary and group documents', icon: FileText },
  { route: '/(coordinator)/operations/incidents' as const, label: 'Incidents', description: 'Report an operational incident', icon: FileWarning },
  { route: '/(coordinator)/operations/updates' as const, label: 'Updates', description: 'Announcements and emergency alerts', icon: Bell },
  { route: '/(coordinator)/operations/profile' as const, label: 'Profile', description: 'Account details and secure sign out', icon: UserRound },
];

export default function CoordinatorMoreScreen() {
  const router = useRouter();
  const trips = useCoordinatorTrips();
  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader eyebrow="Selected trip" title="More operations" subtitle={trips.selectedTrip?.name || 'Coordinator tools'} />
      {operations.map(({ route, label, description, icon: Icon }) => (
        <Pressable key={route} accessibilityRole="button" onPress={() => router.push(route)} style={({ pressed }) => pressed && styles.pressed}>
          <GlassCard style={styles.card}>
            <View style={styles.icon}><Icon color={colors.blueDeep} size={21} /></View>
            <View style={styles.text}><Text style={styles.title}>{label}</Text><Text style={styles.description}>{description}</Text></View>
            <ChevronRight color={colors.inkMuted} size={20} />
          </GlassCard>
        </Pressable>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.md },
  card: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md, padding: spacing.md },
  icon: { width: 42, height: 42, borderRadius: 15, backgroundColor: colors.blueSoft, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 2 },
  title: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  description: { color: colors.inkMuted, fontSize: 12 },
  pressed: { opacity: 0.7 },
});
