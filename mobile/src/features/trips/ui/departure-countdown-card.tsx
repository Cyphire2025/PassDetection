import { format, parseISO } from 'date-fns';
import CalendarDays from 'lucide-react-native/icons/calendar-days';
import Clock3 from 'lucide-react-native/icons/clock-3';
import PlaneTakeoff from 'lucide-react-native/icons/plane-takeoff';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';
import { departureCountdown, tripDayState } from '@/features/trips/data/departure-countdown';

function ordinal(value: number) {
  const remainder100 = value % 100;
  if (remainder100 >= 11 && remainder100 <= 13) return `${value}th`;
  if (value % 10 === 1) return `${value}st`;
  if (value % 10 === 2) return `${value}nd`;
  if (value % 10 === 3) return `${value}rd`;
  return `${value}th`;
}

function CountdownUnit({ value, label }: { value: number; label: string }) {
  return (
    <View style={styles.unit}>
      <Text style={styles.unitValue}>{String(value).padStart(2, '0')}</Text>
      <Text style={styles.unitLabel}>{label}</Text>
    </View>
  );
}

export function DepartureCountdownCard({
  travelDate,
  returnDate,
}: {
  travelDate: string | null;
  returnDate: string | null;
}) {
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (!travelDate) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [travelDate]);

  const countdown = useMemo(
    () => travelDate ? departureCountdown(travelDate, now) : null,
    [now, travelDate],
  );
  const tripDay = useMemo(
    () => travelDate ? tripDayState(travelDate, returnDate, now) : null,
    [now, returnDate, travelDate],
  );
  const parsedTravelDate = travelDate ? parseISO(travelDate) : null;
  const validTravelDate = parsedTravelDate && !Number.isNaN(parsedTravelDate.getTime())
    ? parsedTravelDate
    : null;
  const parsedReturnDate = returnDate ? parseISO(returnDate) : null;
  const validReturnDate = parsedReturnDate && !Number.isNaN(parsedReturnDate.getTime())
    ? parsedReturnDate
    : null;

  return (
    <LinearGradient colors={['#E8F7FD', '#D8EEF8', '#E9F8F9']} end={{ x: 1, y: 1 }} style={styles.card}>
      <View pointerEvents="none" style={styles.glow} />
      <View style={styles.topRow}>
        <View style={styles.labelRow}>
          <View style={styles.icon}><PlaneTakeoff color={colors.blueDeep} size={20} /></View>
          <Text style={styles.label}>Departure</Text>
        </View>
        {countdown && !countdown.complete ? (
          <View style={styles.daysChip}>
            <CalendarDays color={colors.blueDeep} size={14} />
            <Text style={styles.daysText}>
              {countdown.calendarDays === 0
                ? 'Today'
                : `${countdown.calendarDays} ${countdown.calendarDays === 1 ? 'day' : 'days'} left`}
            </Text>
          </View>
        ) : tripDay ? (
          <View style={styles.daysChip}>
            <CalendarDays color={colors.blueDeep} size={14} />
            <Text style={styles.daysText}>
              {tripDay.phase === 'underway' ? `Trip day ${tripDay.dayNumber}` : 'Trip completed'}
            </Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.date}>
        {validTravelDate ? format(validTravelDate, 'EEE, d MMM yyyy') : 'Dates being prepared'}
      </Text>
      {validReturnDate ? <Text style={styles.returnDate}>Returns {format(validReturnDate, 'd MMM yyyy')}</Text> : null}
      <View style={styles.divider} />
      {countdown && !countdown.complete ? (
        <View accessibilityRole="timer" accessibilityLabel={`${countdown.calendarDays} days until departure`} style={styles.countdownRow}>
          <Clock3 color={colors.aqua} size={18} />
          <CountdownUnit value={countdown.days} label="days" />
          <Text style={styles.separator}>:</Text>
          <CountdownUnit value={countdown.hours} label="hrs" />
          <Text style={styles.separator}>:</Text>
          <CountdownUnit value={countdown.minutes} label="min" />
          <Text style={styles.separator}>:</Text>
          <CountdownUnit value={countdown.seconds} label="sec" />
        </View>
      ) : (
        <View style={styles.tripState}>
          <Clock3 color={colors.blueDeep} size={17} />
          <Text style={styles.tripStateText}>
            {tripDay?.phase === 'underway'
              ? `Your ${ordinal(tripDay.dayNumber)} trip day is underway`
              : tripDay?.phase === 'completed'
                ? `Trip completed after ${tripDay.dayNumber} ${tripDay.dayNumber === 1 ? 'day' : 'days'}`
                : 'Countdown appears when dates are confirmed'}
          </Text>
        </View>
      )}
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  card: {
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(23,109,148,0.2)',
    borderRadius: radii.lg,
    padding: spacing.lg,
    shadowColor: colors.blueDeep,
    shadowOpacity: 0.1,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
  glow: { position: 'absolute', width: 130, height: 130, borderRadius: 65, right: -42, top: -68, backgroundColor: colors.aqua, opacity: 0.14 },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  icon: { width: 36, height: 36, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.78)' },
  label: { color: colors.blueDeep, fontSize: 12, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1.1 },
  daysChip: { minHeight: 30, flexDirection: 'row', alignItems: 'center', gap: spacing.xs, borderRadius: radii.pill, backgroundColor: 'rgba(255,255,255,0.72)', paddingHorizontal: spacing.sm },
  daysText: { color: colors.blueDeep, fontSize: 11, fontWeight: '900' },
  date: { marginTop: spacing.md, color: colors.ink, fontSize: 22, lineHeight: 28, fontWeight: '900', letterSpacing: -0.3 },
  returnDate: { marginTop: 2, color: colors.inkMuted, fontSize: 14 },
  divider: { height: StyleSheet.hairlineWidth, marginVertical: spacing.md, backgroundColor: 'rgba(23,109,148,0.22)' },
  countdownRow: { minHeight: 54, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.xs, borderRadius: radii.md, backgroundColor: colors.navy, paddingHorizontal: spacing.md },
  unit: { minWidth: 35, alignItems: 'center' },
  unitValue: { color: colors.white, fontSize: 17, fontWeight: '900', fontVariant: ['tabular-nums'] },
  unitLabel: { color: 'rgba(255,255,255,0.62)', fontSize: 8, fontWeight: '700', textTransform: 'uppercase' },
  separator: { color: colors.aqua, fontSize: 17, fontWeight: '900' },
  tripState: { minHeight: 42, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  tripStateText: { color: colors.blueDeep, fontSize: 13, fontWeight: '800' },
});
