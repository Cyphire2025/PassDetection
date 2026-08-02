import { Tabs } from 'expo-router';

import { FloatingTabBar } from '@/design/navigation/floating-tab-bar';

export default function ManagerTabs() {
  return (
    <Tabs
      initialRouteName="groups"
      tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{ headerShown: false, lazy: true, freezeOnBlur: true }}>
      <Tabs.Screen name="groups" options={{ title: 'Groups' }} />
      <Tabs.Screen name="itinerary" options={{ title: 'Itinerary' }} />
      <Tabs.Screen name="readiness" options={{ title: 'Readiness' }} />
      <Tabs.Screen name="updates" options={{ title: 'Updates' }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
