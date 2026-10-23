import { describe, expect, it } from "vitest";
import nextConfig from "./next.config";
import { VISA_FACE_DETECTION_ASSET_VERSION, visaFaceDetectionAssetUrl } from "./config/visa-face-detection-assets";

describe("Next response policy", () => {
  it("caches immutable public scene files without making assistant pages or APIs cacheable", async () => {
    const entries = await nextConfig.headers?.();
    const scenes = entries!.filter((entry) => entry.source.startsWith("/ai/") && entry.headers.some((header) => header.value.includes("immutable")));
    expect(scenes).toHaveLength(9);
    expect(scenes.filter((scene) => scene.headers.some((header) => header.key === "Content-Encoding" && header.value === "gzip"))).toHaveLength(6);
    for (const scene of scenes) expect(scene.source).toMatch(/^\/ai\/(human-head|test-landscape)\/[a-z0-9-]+-[a-f0-9]{12}\.(bin(\.gz)?|webp)$/);
    expect(entries!.some((entry) => ["/ai", "/api/:path*"].includes(entry.source) && entry.headers.some((header) => header.value.includes("public")))).toBe(false);
  });
  it("caches only explicitly versioned face assets while unversioned assets revalidate", async () => {
    const headers = await nextConfig.headers?.();
    const versioned = headers?.find((entry) => entry.source === "/mediapipe/face_detection/:path*");
    expect(versioned?.has).toEqual([{ type: "query", key: "v", value: VISA_FACE_DETECTION_ASSET_VERSION }]);
    expect(versioned?.headers).toContainEqual({ key: "Cache-Control", value: "public, max-age=86400, immutable" });
    expect(headers?.find((entry) => entry.source === "/mediapipe/:path*")?.headers).toContainEqual({
      key: "Cache-Control", value: "public, max-age=0, must-revalidate",
    });
    expect(visaFaceDetectionAssetUrl("face_detection_short_range.tflite")).toBe(
      `/mediapipe/face_detection/face_detection_short_range.tflite?v=${VISA_FACE_DETECTION_ASSET_VERSION}`,
    );
  });
  it("keeps dynamic pages private while explicitly revalidating public offline assets", async () => {
    const headers = await nextConfig.headers?.();
    if (!headers) throw new Error("Next headers are required");
    const dynamic = headers.find((entry) => entry.source.startsWith("/((?!_next/static"));
    const offline = headers.find((entry) => entry.source === "/offline.html");
    const worker = headers.find((entry) => entry.source === "/sw.js");

    expect(dynamic?.headers).toContainEqual({
      key: "Cache-Control",
      value: "private, no-store, max-age=0, must-revalidate",
    });
    expect(offline?.headers).toContainEqual({
      key: "Cache-Control",
      value: "public, max-age=0, must-revalidate",
    });
    expect(worker?.headers).toContainEqual({ key: "Service-Worker-Allowed", value: "/" });
    expect(headers.findIndex((entry) => entry.source === "/offline.html")).toBeGreaterThan(
      headers.findIndex((entry) => entry.source.startsWith("/((?!_next/static")),
    );
  });
});
