import type { ConfigContext, ExpoConfig } from 'expo/config';

const APP_ID = 'com.globalconnects.groupcompanion';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'Group Companion',
  slug: 'group-companion',
  owner: process.env.EXPO_PUBLIC_EXPO_OWNER || undefined,
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/images/gc-app-icon.png',
  scheme: 'groupcompanion',
  userInterfaceStyle: 'light',
  runtimeVersion: { policy: 'appVersion' },
  updates: {
    enabled: true,
    checkAutomatically: 'ON_LOAD',
    fallbackToCacheTimeout: 0,
    url: process.env.EXPO_PUBLIC_UPDATES_URL || undefined,
  },
  assetBundlePatterns: ['assets/**/*'],
  ios: {
    bundleIdentifier: APP_ID,
    buildNumber: '1',
    supportsTablet: true,
    requireFullScreen: false,
    usesAppleSignIn: false,
    icon: './assets/images/gc-app-icon.png',
    infoPlist: {
      NSCameraUsageDescription:
        'Coordinators use the camera to scan passenger attendance QR codes.',
      NSFaceIDUsageDescription:
        'Use Face ID to unlock your encrypted trip information on this device.',
      UIFileSharingEnabled: false,
      LSSupportsOpeningDocumentsInPlace: false,
      ITSAppUsesNonExemptEncryption: false,
    },
    associatedDomains: ['applinks:app.globalconnecttravels.com'],
  },
  android: {
    package: APP_ID,
    versionCode: 1,
    allowBackup: false,
    permissions: [
      'android.permission.CAMERA',
      'android.permission.POST_NOTIFICATIONS',
      'android.permission.USE_BIOMETRIC',
      'android.permission.USE_FINGERPRINT',
      'android.permission.RECEIVE_BOOT_COMPLETED',
      'android.permission.VIBRATE',
    ],
    intentFilters: [
      {
        action: 'VIEW',
        autoVerify: true,
        data: [
          {
            scheme: 'https',
            host: 'app.globalconnecttravels.com',
            pathPrefix: '/gc',
          },
        ],
        category: ['BROWSABLE', 'DEFAULT'],
      },
    ],
    adaptiveIcon: {
      backgroundColor: '#006FB5',
      foregroundImage: './assets/images/gc-app-monochrome.png',
      monochromeImage: './assets/images/gc-app-monochrome.png',
    },
    predictiveBackGestureEnabled: true,
  },
  web: {
    output: 'static',
    favicon: './assets/images/gc-app-icon.png',
  },
  plugins: [
    'expo-router',
    [
      'expo-splash-screen',
      {
        backgroundColor: '#006FB5',
        image: './assets/images/gc-app-monochrome.png',
        imageWidth: 112,
      },
    ],
    [
      'expo-secure-store',
      {
        configureAndroidBackup: false,
        faceIDPermission:
          'Use Face ID to unlock your encrypted trip information on this device.',
      },
    ],
    ['expo-sqlite', { useSQLCipher: true, enableFTS: true }],
    [
      'expo-local-authentication',
      {
        faceIDPermission:
          'Use Face ID to unlock your encrypted trip information on this device.',
      },
    ],
    [
      'expo-camera',
      {
        cameraPermission:
          'Coordinators use the camera to scan passenger attendance QR codes.',
        recordAudioAndroid: false,
      },
    ],
    [
      'expo-notifications',
      {
        icon: './assets/images/gc-app-monochrome.png',
        color: '#CACF42',
        defaultChannel: 'trip-updates',
      },
    ],
    'expo-background-task',
    'expo-sharing',
    [
      'expo-build-properties',
      {
        android: {
          minSdkVersion: 26,
          usesCleartextTraffic: false,
          enableMinifyInReleaseBuilds: true,
          enableShrinkResourcesInReleaseBuilds: true,
          networkInspector: false,
        },
        ios: {
          deploymentTarget: '16.4',
          useFrameworks: 'static',
        },
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    eas: {
      projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID || undefined,
    },
  },
});
