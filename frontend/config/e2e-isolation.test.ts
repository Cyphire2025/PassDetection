import { describe, expect, it } from "vitest";
import {
  E2E_API_ORIGIN,
  isolatedE2eProcessEnvironment,
} from "./e2e-isolation";

describe("Playwright process isolation", () => {
  it("overrides both server and legacy public API destinations", () => {
    const environment = isolatedE2eProcessEnvironment({
      PATH: "preserved-path",
      API_BASE_URL: "https://production.example.test",
      NEXT_PUBLIC_API_BASE_URL: "http://192.168.1.4:8000",
    });

    expect(environment.PATH).toBe("preserved-path");
    expect(environment.API_BASE_URL).toBe(E2E_API_ORIGIN);
    expect(environment.NEXT_PUBLIC_API_BASE_URL).toBe(E2E_API_ORIGIN);
    expect(JSON.stringify(environment)).not.toContain("192.168.1.4");
    expect(JSON.stringify(environment)).not.toContain("production.example.test");
  });
});
