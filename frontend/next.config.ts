/**
 * Next.js Configuration — PassDetection Platform
 */

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
  // Only active when NEXT_PUBLIC_API_BASE_URL is set.
  // In production, Nginx routes /api/* to the backend directly.
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
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
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=self, microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
