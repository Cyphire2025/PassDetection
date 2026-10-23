/**
 * Next.js Configuration — Global Connects Dashboard
 */

import type { NextConfig } from "next";
import { resolveApiRewriteBase } from "./config/api-routing";
import { VISA_FACE_DETECTION_ASSET_VERSION } from "./config/visa-face-detection-assets";
import particleAssets from "./public/ai/human-head/particles-v1.json";
import landscapeAssets from "./public/ai/test-landscape/compact-v1.json";

const PRIVATE_DYNAMIC_CACHE_CONTROL = "private, no-store, max-age=0, must-revalidate";
const PUBLIC_REVALIDATED_CACHE_CONTROL = "public, max-age=0, must-revalidate";
const PUBLIC_REVALIDATED_ASSETS = [
  "/offline.html",
  "/offline-scanner.js",
  "/offline/vendor/:path*",
  "/manifest.webmanifest",
  "/email-automation.webmanifest",
  "/pwa-icon.svg",
  "/pwa-icon-192.png",
  "/pwa-icon-512.png",
  "/pwa-icon-maskable-512.png",
  "/apple-touch-icon.png",
  "/globalconnect-logo.png",
  "/globalconnect-logo-transparent.png",
  "/assets/branding/global-connect/:path*",
  "/mediapipe/:path*",
] as const;

const nextConfig: NextConfig = {
  // Playwright and physical-device LAN development may address the local dev
  // server by loopback IP. Keep that one exact origin explicit so Next's HMR
  // and RSC development endpoints remain protected from arbitrary origins.
  allowedDevOrigins: ["127.0.0.1"],

  // ── TypeScript ───────────────────────────────────────────
  typescript: {
    ignoreBuildErrors: false,
  },

  // ── Typed Routes ─────────────────────────────────────────
  typedRoutes: true,

  // ── Docker Output Standalone ─────────────────────────────
  output: "standalone",

  // ── Image Optimisation ───────────────────────────────────
  images: {
    remotePatterns: [
      {
        protocol: "http",
        hostname: "localhost",
        port: "9000",
        pathname: "/**",
      },
    ],
    formats: ["image/avif", "image/webp"],
  },

  // ── API Proxy (development rewrites) ─────────────────────
  // Production prefers Nginx same-origin routing. An optional server-only
  // API_BASE_URL enables a Next-side rewrite without exposing the upstream.
  async rewrites() {
    const apiBase = resolveApiRewriteBase({
      NODE_ENV: process.env.NODE_ENV,
      API_BASE_URL: process.env.API_BASE_URL,
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    });
    if (!apiBase) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      { source: "/oauth/mcp/:path*", destination: `${apiBase}/oauth/mcp/:path*` },
      { source: "/mcp/native-transfers/:path*", destination: `${apiBase}/mcp/native-transfers/:path*` },
    ];
  },

  // ── Security Headers ──────────────────────────────────────
  async headers() {
    return [
      {
        source: "/((?!_next/static|_next/image|favicon.ico).*)",
        headers: [
          {
            key: "Cache-Control",
            value: PRIVATE_DYNAMIC_CACHE_CONTROL,
          },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=self, microphone=(), geolocation=()",
          },
        ],
      },
      ...PUBLIC_REVALIDATED_ASSETS.map((source) => ({
        source,
        headers: [{
          key: "Cache-Control",
          value: PUBLIC_REVALIDATED_CACHE_CONTROL,
        }],
      })),
      // Only these public, content-addressed scene files are immutable. Account
      // pages, APIs and all other assets retain their existing cache policy.
      ...[
        ...Object.values(particleAssets.assets).map(({ file }) => `/ai/human-head/${file}`),
        ...Object.values(landscapeAssets).map(({ file }) => `/ai/test-landscape/${file}`),
      ].map((source) => ({ source, headers: [
        { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ...(source.endsWith(".bin.gz") ? [{ key: "Content-Encoding", value: "gzip" }, { key: "Content-Type", value: "application/octet-stream" }] : []),
      ] })),
      {
        source: "/mediapipe/face_detection/:path*",
        has: [{ type: "query", key: "v", value: VISA_FACE_DETECTION_ASSET_VERSION }],
        headers: [{ key: "Cache-Control", value: "public, max-age=86400, immutable" }],
      },
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: PUBLIC_REVALIDATED_CACHE_CONTROL },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      { source: "/mcp/connect", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] },
      { source: "/mcp/file-transfer/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] },
    ];
  },
};

export default nextConfig;
