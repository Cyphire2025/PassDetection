import type { LucideIcon } from 'lucide-react-native';
import Bell from 'lucide-react-native/icons/bell';
import ChartNoAxesCombined from 'lucide-react-native/icons/chart-no-axes-combined';
import CircleUserRound from 'lucide-react-native/icons/circle-user-round';
import ClipboardCheck from 'lucide-react-native/icons/clipboard-check';
import FileLock2 from 'lucide-react-native/icons/file-lock';
import MapPinned from 'lucide-react-native/icons/map-pinned';
import PlaneTakeoff from 'lucide-react-native/icons/plane-takeoff';
import QrCode from 'lucide-react-native/icons/qr-code';
import Route from 'lucide-react-native/icons/route';
import ScanLine from 'lucide-react-native/icons/scan-line';
import UsersRound from 'lucide-react-native/icons/users-round';
import { BlurView } from 'expo-blur';
import * as Device from 'expo-device';
import { Tabs } from 'expo-router';
import { useEffect, useState, type ComponentProps } from 'react';
import { AccessibilityInfo, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radii, spacing } from '@/design/theme';

type BottomTabBarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>['tabBar']>>[0];

const iconByRoute: Record<string, LucideIcon> = {
  trip: PlaneTakeoff,
  documents: FileLock2,
  qr: QrCode,
  updates: Bell,
  more: CircleUserRound,
  groups: MapPinned,
  itinerary: Route,
  readiness: ChartNoAxesCombined,
  profile: CircleUserRound,
  passengers: UsersRound,
  scan: ScanLine,
  attendance: ClipboardCheck,
};

export function FloatingTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const [reduceTransparency, setReduceTransparency] = useState(false);

  useEffect(() => {
    void AccessibilityInfo.isReduceTransparencyEnabled().then(setReduceTransparency);
    const subscription = AccessibilityInfo.addEventListener(
      'reduceTransparencyChanged',
      setReduceTransparency,
    );
    return () => subscription.remove();
  }, []);

  const allowBlur = !reduceTransparency && (Platform.OS === 'ios' || (Device.deviceYearClass ?? 0) >= 2020);
  const content = (
    <View style={styles.items}>
      {state.routes.map((route, index) => {
        const focused = state.index === index;
        const options = descriptors[route.key]?.options;
        const label = typeof options?.title === 'string' ? options.title : route.name;
        const Icon = iconByRoute[route.name] ?? CircleUserRound;
        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityLabel={options?.tabBarAccessibilityLabel ?? label}
            accessibilityState={{ selected: focused }}
            onLongPress={() => navigation.emit({ type: 'tabLongPress', target: route.key })}
            onPress={() => {
              const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!focused && !event.defaultPrevented) navigation.navigate(route.name, route.params);
            }}
            style={({ pressed }) => [styles.item, focused && styles.itemFocused, pressed && styles.pressed]}>
            <Icon color={focused ? colors.navy : 'rgba(255,255,255,0.7)'} size={21} strokeWidth={focused ? 2.7 : 2} />
            <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.label, focused && styles.labelFocused]}>
              {label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );

  return (
    <View pointerEvents="box-none" style={[styles.position, { bottom: Math.max(insets.bottom, spacing.sm) }]}>
      {allowBlur ? (
        <BlurView intensity={52} tint="dark" blurMethod="dimezisBlurViewSdk31Plus" style={styles.bar}>
          {content}
        </BlurView>
      ) : (
        <View style={[styles.bar, styles.fallback]}>{content}</View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  position: { position: 'absolute', left: spacing.md, right: spacing.md },
  bar: {
    overflow: 'hidden',
    borderRadius: radii.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255,255,255,0.16)',
    backgroundColor: 'rgba(8,41,54,0.92)',
    shadowColor: colors.navy,
    shadowOpacity: 0.28,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
  fallback: { backgroundColor: colors.navy },
  items: { minHeight: 68, padding: spacing.xs, flexDirection: 'row', alignItems: 'center' },
  item: {
    flex: 1,
    minHeight: 58,
    minWidth: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radii.md,
    gap: 3,
  },
  itemFocused: { backgroundColor: colors.green },
  pressed: { opacity: 0.65 },
  label: { color: 'rgba(255,255,255,0.68)', fontSize: 10, fontWeight: '700', maxWidth: 70 },
  labelFocused: { color: colors.navy, fontWeight: '900' },
});
