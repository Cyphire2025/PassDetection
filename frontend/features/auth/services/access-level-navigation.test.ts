import { afterEach, describe, expect, it, vi } from "vitest";
import type { User, UserRole } from "@/types";
import { navigateToAccessLevel } from "./access-level-navigation";

describe("access level document navigation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each<[UserRole, string]>([
    ["super_admin", "/dashboard"], ["agency_manager", "/dashboard"],
    ["agency_staff", "/passports"], ["agency_coordinator", "/coordinator"],
  ])("lands %s at %s in a new document", (role, path) => {
    const replace = vi.fn();
    vi.stubGlobal("window", { location: { replace } });
    navigateToAccessLevel({ role, is_active: true } as User);
    expect(replace).toHaveBeenCalledExactlyOnceWith(path);
  });
});
