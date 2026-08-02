import { Tabs } from 'expo-router';

import { FloatingTabBar } from '@/design/navigation/floating-tab-bar';

export default function CoordinatorTabs() {
  return (
    <Tabs
      initialRouteName="groups"
      tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{ headerShown: false, lazy: true, freezeOnBlur: true }}>
      <Tabs.Screen name="groups" options={{ title: 'Trips' }} />
      <Tabs.Screen name="passengers" options={{ title: 'Passengers' }} />
      <Tabs.Screen name="scan" options={{ title: 'Scan' }} />
      <Tabs.Screen name="attendance" options={{ title: 'Attendance' }} />
      <Tabs.Screen name="more" options={{ title: 'More' }} />
    </Tabs>
  );
}
