/**
 * Next.js Configuration — Global Connects Dashboard
 */

import type { NextConfig } from "next";
import { resolveApiRewriteBase } from "./config/api-routing";

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
  "/globalconnectteam.png",
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
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: PUBLIC_REVALIDATED_CACHE_CONTROL },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default nextConfig;
