import { describe, expect, it } from "vitest";
import nextConfig from "./next.config";

describe("Next response policy", () => {
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
