import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import Contact from 'lucide-react-native/icons/contact';
import { useMemo } from 'react';
import {
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import type { CoordinatorPassengerDetail } from '@/features/coordinator/api/coordinator-contracts';

import { OperationHeader } from './operation-header';

type DetailItem = { key?: string; label: string; value: string | null | undefined };
type DetailSection = { title: string; data: DetailItem[] };

export function OperationalPassengerDetail({
  passenger,
  isPending,
  isError,
  isRefreshing,
  onRefresh,
  subtitle,
  errorMessage,
}: {
  passenger: CoordinatorPassengerDetail | undefined;
  isPending: boolean;
  isError: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
  subtitle: string;
  errorMessage: string;
}) {
  const sections = useMemo(
    () => passenger ? passengerDetailSections(passenger) : [],
    [passenger],
  );
  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<DetailItem, DetailSection>
        sections={sections}
        keyExtractor={(item, index) => item.key ?? `${item.label}:${index}`}
        stickySectionHeadersEnabled={false}
        initialNumToRender={18}
        maxToRenderPerBatch={24}
        updateCellsBatchingPeriod={35}
        windowSize={7}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={onRefresh} />}
        ListHeaderComponent={(
          <View style={styles.header}>
            <OperationHeader title="Passenger details" subtitle={subtitle} />
            {isPending ? <ContentLoading label="Loading passenger details" /> : null}
            {isError ? <ContentError message={errorMessage} onRetry={onRefresh} /> : null}
            {passenger ? <PassengerIdentity passenger={passenger} /> : null}
          </View>
        )}
        renderSectionHeader={({ section }) => (
          <View style={styles.sectionHeaderCard}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
          </View>
        )}
        renderSectionFooter={() => <View style={styles.sectionFooter} />}
        renderItem={({ item }: SectionListRenderItemInfo<DetailItem, DetailSection>) => (
          <View style={styles.row}>
            <Text style={styles.label}>{item.label}</Text>
            <Text selectable style={styles.value}>{item.value}</Text>
          </View>
        )}
        ListFooterComponent={passenger?.has_alert ? (
          <GlassCard style={styles.alertCard}>
            <AlertTriangle color={colors.warning} size={22} />
            <View style={styles.alertText}>
              <Text style={styles.alertTitle}>Important alert</Text>
              <Text style={styles.alertMessage}>Review this passenger with the operations team.</Text>
            </View>
          </GlassCard>
        ) : null}
      />
    </Screen>
  );
}

function PassengerIdentity({ passenger }: { passenger: CoordinatorPassengerDetail }) {
  return (
    <View style={styles.identity}>
      <View style={styles.avatar}><Contact color={colors.greenDeep} size={32} /></View>
      <Text accessibilityRole="header" style={styles.name}>{passenger.display_name}</Text>
      <Text style={styles.employee}>{passenger.employee_code || 'Employee code not provided'}</Text>
    </View>
  );
}

function passengerDetailSections(passenger: CoordinatorPassengerDetail): DetailSection[] {
  const importedDetails = passenger.additional_details
    .filter((item) => item.source === 'imported')
    .map((item) => ({ key: item.key, label: item.label, value: item.value }));
  const configuredDetails = passenger.additional_details
    .filter((item) => item.source !== 'imported')
    .map((item) => ({ key: item.key, label: item.label, value: item.value }));
  const sections: DetailSection[] = [
    {
      title: 'Work and contact',
      data: [
        { label: 'Staff code', value: passenger.staff_code },
        { label: 'Employee type', value: passenger.employee_type },
        { label: 'Company / dealership', value: passenger.agency_dealership_name },
        { label: 'Base city', value: passenger.base_city },
        { label: 'Zone', value: passenger.zone_name },
        { label: 'Designation', value: passenger.designation },
        { label: 'Department', value: passenger.department },
        { label: 'Phone', value: passenger.phone_number },
        { label: 'Email', value: passenger.email },
      ],
    },
    {
      title: 'Travel and personal',
      data: [
        { label: 'Departure city', value: passenger.departure_city },
        { label: 'Nearest domestic airport', value: passenger.nearest_domestic_airport },
        { label: 'Nationality', value: passenger.nationality },
        { label: 'Gender', value: passenger.gender },
        { label: 'Date of birth', value: formatDate(passenger.date_of_birth) },
      ],
    },
    {
      title: 'Passport details',
      data: [
        { label: 'Surname', value: passenger.passport_surname },
        { label: 'Given names', value: passenger.passport_given_names },
        { label: 'Place of issue', value: passenger.passport_place_of_issue },
        { label: 'Issuing country', value: passenger.passport_issuing_country },
        { label: 'Date of issue', value: formatDate(passenger.passport_date_of_issue) },
        { label: 'Date of expiry', value: formatDate(passenger.passport_date_of_expiry) },
      ],
    },
    {
      title: 'Stay and meals',
      data: [
        { label: 'Hotel', value: passenger.hotel_name },
        { label: 'Room', value: passenger.room_number },
        { label: 'Roommate(s)', value: passenger.roommate_summary },
        { label: 'Meal preference', value: passenger.meal_preference },
      ],
    },
    {
      title: 'Family contact',
      data: [
        { label: 'Verified relationship', value: passenger.qualifier_relation },
        { label: 'Relationship', value: passenger.family_relation },
        { label: 'Family head', value: passenger.family_head_name },
        { label: 'Family head phone', value: passenger.family_head_phone },
        { label: 'Family head email', value: passenger.family_head_email },
      ],
    },
    {
      title: 'Emergency contact',
      data: [
        { label: 'Name', value: passenger.emergency_contact_name },
        { label: 'Phone', value: passenger.emergency_contact_phone },
        { label: 'Relationship', value: passenger.emergency_contact_relation },
      ],
    },
    {
      title: 'Document availability',
      data: [
        { label: 'Passport', value: documentStatusLabel(passenger.passport_status) },
        { label: 'Visa', value: documentStatusLabel(passenger.visa_status) },
        { label: 'Flight ticket', value: documentStatusLabel(passenger.flight_ticket_status) },
        { label: 'Insurance', value: documentStatusLabel(passenger.insurance_status) },
        { label: 'Hotel voucher', value: documentStatusLabel(passenger.hotel_voucher_status) },
        { label: 'Other document', value: documentStatusLabel(passenger.other_document_status) },
      ],
    },
    {
      title: 'Record status',
      data: [
        { label: 'Attendance', value: humanizeStatus(passenger.attendance_status) },
        { label: 'Submission type', value: humanizeStatus(passenger.submission_mode) },
        { label: 'Submission status', value: humanizeStatus(passenger.submission_status) },
        { label: 'Last updated', value: formatDateTime(passenger.updated_at) },
      ],
    },
    { title: 'Imported operational details', data: importedDetails },
    { title: 'Custom trip details', data: configuredDetails },
    { title: 'Operational remarks', data: [{ label: 'Remarks', value: passenger.operational_remarks }] },
  ];
  return sections.map((section) => ({
    ...section,
    data: section.data
      .filter((item) => item.value?.trim())
      .map((item, index) => ({
        ...item,
        key: `${section.title}:${item.key ?? item.label}:${index}`,
      })),
  })).filter((section) => section.data.length > 0);
}

function documentStatusLabel(status: 'available' | 'not_available'): string {
  return status === 'available' ? 'Available' : 'Not available';
}

function humanizeStatus(value: string): string {
  const normalized = value.replaceAll('_', ' ').trim();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : value;
}

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const [year, month, day] = value.split('-');
  return year && month && day ? `${day}/${month}/${year}` : value;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  header: { gap: spacing.xl, paddingBottom: spacing.sm },
  identity: { alignItems: 'center', gap: spacing.sm },
  avatar: { width: 72, height: 72, borderRadius: 28, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.greenSoft },
  name: { color: colors.ink, fontSize: 23, fontWeight: '900', textAlign: 'center' },
  employee: { color: colors.inkMuted, fontSize: 13, textAlign: 'center' },
  sectionHeaderCard: { marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.sm, backgroundColor: colors.surface, borderColor: colors.border, borderWidth: StyleSheet.hairlineWidth, borderBottomWidth: 0, borderTopLeftRadius: radii.md, borderTopRightRadius: radii.md },
  sectionTitle: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  row: { gap: 4, paddingVertical: spacing.sm, paddingHorizontal: spacing.lg, backgroundColor: colors.surface, borderLeftWidth: StyleSheet.hairlineWidth, borderRightWidth: StyleSheet.hairlineWidth, borderLeftColor: colors.border, borderRightColor: colors.border, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  sectionFooter: { height: spacing.md, backgroundColor: colors.surface, borderColor: colors.border, borderWidth: StyleSheet.hairlineWidth, borderTopWidth: 0, borderBottomLeftRadius: radii.md, borderBottomRightRadius: radii.md },
  label: { color: colors.inkMuted, fontSize: 12, fontWeight: '700' },
  value: { color: colors.ink, fontSize: 15, fontWeight: '700' },
  alertCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md },
  alertText: { flex: 1, gap: 3 },
  alertTitle: { color: colors.ink, fontSize: 15, fontWeight: '900' },
  alertMessage: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
