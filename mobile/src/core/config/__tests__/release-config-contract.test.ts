import type { ConfigContext, ExpoConfig } from "expo/config";

import eas from "../../../../eas.json";
import createExpoConfig from "../../../../app.config";

describe("mobile release configuration", () => {
  it("isolates OTA updates by native fingerprint and removes unused iOS permissions", () => {
    const config = createExpoConfig({
      config: {} as ExpoConfig,
    } as ConfigContext);

    expect(config.name).toBe("Global Connect Travels");
    expect(config.slug).toBe("group-companion");
    expect(config.runtimeVersion).toEqual({ policy: "fingerprint" });
    expect(config.updates?.enabled).toBe(false);
    expect(config.updates).toMatchObject({
      checkAutomatically: "ON_LOAD",
      fallbackToCacheTimeout: 0,
      useEmbeddedUpdate: true,
      disableAntiBrickingMeasures: false,
    });
    expect(config.plugins).toContain("expo-image");
    expect(config.plugins).toContainEqual(["@sentry/react-native/expo", {}]);
    expect(config.plugins).toContainEqual([
      "expo-secure-store",
      {
        configureAndroidBackup: false,
        faceIDPermission: false,
      },
    ]);
    expect(config.plugins).toContainEqual([
      "expo-camera",
      {
        cameraPermission:
          "Coordinators use the camera to scan passenger attendance QR codes.",
        microphonePermission: false,
        recordAudioAndroid: false,
      },
    ]);
    expect(config.ios?.associatedDomains).toEqual([
      "applinks:tech.gctravels.com",
    ]);
    expect(config.icon).toBe("./assets/images/gc-app-icon.png");
    expect(config.ios?.icon).toBe("./assets/images/gc-app-icon.png");
    expect(config.android?.adaptiveIcon).toEqual({
      backgroundColor: "#056BB1",
      foregroundImage: "./assets/images/gc-app-icon.png",
      monochromeImage: "./assets/images/gc-app-monochrome.png",
    });
  });

  it("keeps the store bundle and installable APK on the production EAS environment", () => {
    expect(eas.cli).toMatchObject({
      version: "22.0.0",
      appVersionSource: "remote",
    });
    expect(eas.build.base).toEqual({ node: "20.19.4" });
    expect(eas.build.development).toMatchObject({
      extends: "base",
      environment: "development",
      channel: "development",
    });
    expect(eas.build.preview).toMatchObject({
      extends: "base",
      environment: "preview",
      channel: "preview",
    });
    expect(eas.build.production).toMatchObject({
      extends: "base",
      environment: "production",
      autoIncrement: true,
      channel: "production",
      android: { buildType: "app-bundle" },
    });
    expect(eas.build["production-apk"]).toMatchObject({
      extends: "production",
      distribution: "internal",
      android: { buildType: "apk" },
    });
  });
});
