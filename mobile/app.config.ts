import type { ConfigContext, ExpoConfig } from "expo/config";

import {
  normalizeBuildFilePath,
  validateAppIntegrityBuildEnvironment,
  validateObservabilityBuildEnvironment,
  validateOtaUpdateEnvironment,
  validateProductionPublicEnvironment,
} from "./scripts/production-public-env";

const APP_DISPLAY_NAME = "Global Connect Travels";
const APP_ID = "com.globalconnects.groupcompanion";
const VERIFIED_LINK_HOST = "tech.gctravels.com";
const PRODUCTION_EAS_PROFILES = new Set(["production", "production-apk"]);
const updatesUrl = process.env.EXPO_PUBLIC_UPDATES_URL;
const rawUpdatesCodeSigningCertificate =
  process.env.EXPO_UPDATES_CODE_SIGNING_CERTIFICATE;
const updatesCodeSigningCertificate = normalizeBuildFilePath(
  rawUpdatesCodeSigningCertificate,
);
const googleServicesFile = process.env.GOOGLE_SERVICES_JSON;
const sentryOrganization = process.env.SENTRY_ORG;
const sentryProject = process.env.SENTRY_PROJECT;
const localNetworkDevelopment = process.env.EXPO_PUBLIC_APP_ENV === "development";
const androidFaceLivenessEnabled =
  process.env.GC_ANDROID_FACE_LIVENESS_ENABLED === "true";
const androidFaceLivenessRegion =
  process.env.GC_ANDROID_FACE_LIVENESS_REGION;
const androidFaceLivenessIdentityPoolId =
  process.env.GC_ANDROID_FACE_LIVENESS_IDENTITY_POOL_ID;

const shouldValidateProductionEnvironment =
  process.env.EXPO_PUBLIC_APP_ENV === "production" ||
  process.env.GC_VALIDATE_PRODUCTION_PUBLIC_ENV === "true" ||
  PRODUCTION_EAS_PROFILES.has(process.env.EAS_BUILD_PROFILE ?? "");
const appIntegrityBuild = validateAppIntegrityBuildEnvironment(
  process.env,
  shouldValidateProductionEnvironment,
);

if (shouldValidateProductionEnvironment) {
  validateProductionPublicEnvironment(process.env);
  validateObservabilityBuildEnvironment(process.env);
}
if (updatesUrl || rawUpdatesCodeSigningCertificate) {
  validateOtaUpdateEnvironment(process.env);
}
if (process.env.GC_VALIDATE_ANDROID_PUSH === "true") {
  if (!googleServicesFile) {
    throw new Error(
      "Android push configuration failed: GOOGLE_SERVICES_JSON must point to the protected Firebase google-services.json file.",
    );
  }
}

export default ({ config }: ConfigContext): ExpoConfig => {
  // Expo SDK 57 still consumes the documented top-level jsEngine field, but
  // its TypeScript surface no longer exposes that deprecated switch. Keep the
  // extension explicit so configuration validation and generated native
  // projects continue to prove that both release targets use Hermes.
  const applicationConfig: ExpoConfig & { jsEngine: "hermes" } = {
    ...config,
    name: APP_DISPLAY_NAME,
    slug: "group-companion",
    ...(process.env.EXPO_PUBLIC_EXPO_OWNER
      ? { owner: process.env.EXPO_PUBLIC_EXPO_OWNER }
      : {}),
    version: "1.0.3",
    jsEngine: "hermes",
    orientation: "portrait",
    icon: "./assets/images/gc-app-icon.png",
    scheme: "groupcompanion",
    userInterfaceStyle: "light",
    runtimeVersion: { policy: "fingerprint" },
    updates: {
      enabled: Boolean(updatesUrl),
      checkAutomatically: "ON_LOAD",
      fallbackToCacheTimeout: 0,
      useEmbeddedUpdate: true,
      disableAntiBrickingMeasures: false,
      ...(updatesUrl && updatesCodeSigningCertificate
        ? {
            url: updatesUrl,
            codeSigningCertificate: updatesCodeSigningCertificate,
            codeSigningMetadata: {
              alg: "rsa-v1_5-sha256",
              keyid: "main",
            },
          }
        : {}),
    },
    assetBundlePatterns: ["assets/**/*"],
    ios: {
      bundleIdentifier: APP_ID,
      buildNumber: "1",
      supportsTablet: true,
      requireFullScreen: false,
      usesAppleSignIn: false,
      icon: "./assets/images/gc-app-icon.png",
      infoPlist: {
        NSCameraUsageDescription:
          "Use the camera for attendance QR scanning or, with your consent, to set up Face Scan for My Photos.",
        UIFileSharingEnabled: false,
        LSSupportsOpeningDocumentsInPlace: false,
        ITSAppUsesNonExemptEncryption: false,
        NSAppTransportSecurity: {
          NSAllowsArbitraryLoads: false,
          NSAllowsLocalNetworking: localNetworkDevelopment,
        },
      },
      associatedDomains: [`applinks:${VERIFIED_LINK_HOST}`],
      ...(appIntegrityBuild.appAttestEnvironment
        ? {
            entitlements: {
              "com.apple.developer.devicecheck.appattest-environment":
                appIntegrityBuild.appAttestEnvironment,
            },
          }
        : {}),
    },
    android: {
      package: APP_ID,
      versionCode: 4,
      ...(googleServicesFile ? { googleServicesFile } : {}),
      allowBackup: false,
      blockedPermissions: [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.USE_BIOMETRIC",
        "android.permission.USE_FINGERPRINT",
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.WRITE_SETTINGS",
      ],
      permissions: [
        "android.permission.CAMERA",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.VIBRATE",
      ],
      intentFilters: [
        {
          action: "VIEW",
          autoVerify: true,
          data: [
            {
              scheme: "https",
              host: VERIFIED_LINK_HOST,
              pathPrefix: "/gc",
            },
          ],
          category: ["BROWSABLE", "DEFAULT"],
        },
      ],
      adaptiveIcon: {
        backgroundColor: "#056BB1",
        foregroundImage: "./assets/images/gc-app-icon.png",
        monochromeImage: "./assets/images/gc-app-monochrome.png",
      },
      predictiveBackGestureEnabled: true,
    },
    web: {
      output: "static",
      favicon: "./assets/images/gc-app-icon.png",
    },
    plugins: [
      "./plugins/with-android-release-signing",
      "./plugins/with-android-gradle-wrapper-integrity",
      "./plugins/with-android-unlocked-device-store",
      [
        "./plugins/with-android-face-liveness",
        {
          enabled: androidFaceLivenessEnabled,
          region: androidFaceLivenessRegion,
          identityPoolId: androidFaceLivenessIdentityPoolId,
        },
      ],
      "./plugins/with-expo-headless-loader-proguard",
      [
        "@sentry/react-native/expo",
        {
          ...(sentryOrganization ? { organization: sentryOrganization } : {}),
          ...(sentryProject ? { project: sentryProject } : {}),
        },
      ],
      "expo-router",
      "expo-font",
      "expo-image",
      "expo-sharing",
      "expo-asset",
      [
        "expo-splash-screen",
        {
          backgroundColor: "#CACF42",
          image: "./assets/images/gc-app-monochrome.png",
          imageWidth: 112,
        },
      ],
      [
        "expo-secure-store",
        {
          configureAndroidBackup: false,
          faceIDPermission: false,
        },
      ],
      ["expo-sqlite", { useSQLCipher: true, enableFTS: true }],
      [
        "expo-localization",
        {
          // English is the only human-reviewed catalog today. RTL remains
          // enabled at the native boundary so a complete reviewed RTL catalog
          // can be added without another platform capability migration.
          supportedLocales: { ios: ["en"], android: ["en"] },
          supportsRTL: true,
          allowDynamicLocaleChangesAndroid: true,
        },
      ],
      [
        "expo-camera",
        {
          cameraPermission:
            "Use the camera for attendance QR scanning or, with your consent, to set up Face Scan for My Photos.",
          microphonePermission: false,
          recordAudioAndroid: false,
        },
      ],
      [
        "expo-audio",
        {
          microphonePermission: false,
          recordAudioAndroid: false,
          enableBackgroundRecording: false,
          enableBackgroundPlayback: false,
        },
      ],
      [
        "expo-notifications",
        {
          icon: "./assets/images/gc-app-monochrome.png",
          color: "#CACF42",
          defaultChannel: "trip-updates",
        },
      ],
      "expo-background-task",
      [
        "expo-build-properties",
        {
          android: {
            minSdkVersion: 26,
            ...(androidFaceLivenessEnabled ? { kotlinVersion: "2.2.0" } : {}),
            usesCleartextTraffic: false,
            enableMinifyInReleaseBuilds: true,
            enableShrinkResourcesInReleaseBuilds: true,
            networkInspector: false,
          },
          ios: {
            deploymentTarget: "16.4",
            useFrameworks: "static",
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
  };
  return applicationConfig;
};
