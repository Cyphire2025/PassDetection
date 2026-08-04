import type { ConfigContext, ExpoConfig } from 'expo/config';

import { validateProductionPublicEnvironment } from './scripts/production-public-env';

const APP_ID = 'com.globalconnects.groupcompanion';
const PRODUCTION_EAS_PROFILES = new Set(['production', 'production-apk']);
const updatesUrl = process.env.EXPO_PUBLIC_UPDATES_URL;

const shouldValidateProductionEnvironment =
  process.env.EXPO_PUBLIC_APP_ENV === 'production' ||
  process.env.GC_VALIDATE_PRODUCTION_PUBLIC_ENV === 'true' ||
  PRODUCTION_EAS_PROFILES.has(process.env.EAS_BUILD_PROFILE ?? '');

if (shouldValidateProductionEnvironment) {
  validateProductionPublicEnvironment(process.env);
}

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
  runtimeVersion: { policy: 'fingerprint' },
  updates: {
    enabled: Boolean(updatesUrl),
    checkAutomatically: 'ON_LOAD',
    fallbackToCacheTimeout: 0,
    url: updatesUrl || undefined,
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
    blockedPermissions: [
      'android.permission.READ_EXTERNAL_STORAGE',
      'android.permission.WRITE_EXTERNAL_STORAGE',
      'android.permission.READ_MEDIA_IMAGES',
      'android.permission.USE_BIOMETRIC',
      'android.permission.USE_FINGERPRINT',
      'android.permission.SYSTEM_ALERT_WINDOW',
      'android.permission.WRITE_SETTINGS',
    ],
    permissions: [
      'android.permission.CAMERA',
      'android.permission.POST_NOTIFICATIONS',
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
      backgroundColor: '#CACF42',
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
    './plugins/with-expo-headless-loader-proguard',
    'expo-router',
    [
      'expo-splash-screen',
      {
        backgroundColor: '#CACF42',
        image: './assets/images/gc-app-monochrome.png',
        imageWidth: 112,
      },
    ],
    [
      'expo-secure-store',
      {
        configureAndroidBackup: false,
        faceIDPermission: false,
      },
    ],
    ['expo-sqlite', { useSQLCipher: true, enableFTS: true }],
    [
      'expo-camera',
      {
        cameraPermission:
          'Coordinators use the camera to scan passenger attendance QR codes.',
        microphonePermission: false,
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
