import { Tabs } from 'expo-router';

import { FloatingTabBar } from '@/design/navigation/floating-tab-bar';

export default function PassengerTabs() {
  return (
    <Tabs
      initialRouteName="trip"
      tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{ headerShown: false, lazy: true, freezeOnBlur: true }}>
      <Tabs.Screen name="trip" options={{ title: 'Trip' }} />
      <Tabs.Screen name="documents" options={{ title: 'Documents' }} />
      <Tabs.Screen name="qr" options={{ title: 'My QR' }} />
      <Tabs.Screen name="updates" options={{ title: 'Updates' }} />
      <Tabs.Screen name="more" options={{ title: 'More' }} />
    </Tabs>
  );
}
