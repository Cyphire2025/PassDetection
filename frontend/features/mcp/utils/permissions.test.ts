import { expect, it } from "vitest";
import { connectionFixture, permissionFixture } from "./permissions.test-fixture";
import { deviceWriteSections, hasWriteScope, permissionUpdate, samePermissionUpdate, validConnectionPermissions, validPermissions, writeToolsForSections } from "./permissions";
import { hasPermission } from "../components/mcp-access-model";

it("derives tools only after all their reviewed sections are allowed", () => {
  const data = permissionFixture();
  expect(writeToolsForSections(data, ["group_links"])).toEqual(["create_native_upload"]);
  expect(writeToolsForSections(data, ["group_links", "all_groups"])).toEqual(["configure_group_link", "create_group", "create_native_upload"]);
  expect(writeToolsForSections(data, [])).toEqual(["create_native_upload"]);
});

it("recognizes every effectful OAuth family without treating diagnostic permission as write authority", () => {
  for (const scope of ["mcp:change", "mcp:export", "mcp:upload", "mcp:communicate"] as const) expect(hasWriteScope([scope])).toBe(true);
  expect(hasWriteScope(["mcp:read", "mcp:diagnose"])).toBe(false);
});

it("accepts saved disabled write settings on a read-only deployment and preserves read choices", () => {
  const data = permissionFixture({ write_available: false });
  expect(validPermissions(data)).toBe(true);
  const update = permissionUpdate(data);
  expect(update).toMatchObject({ expected_revision: 7, read_enabled: true, write_enabled: false, allowed_read_sections: ["all_groups", "menu"] });
  expect(samePermissionUpdate(update, permissionUpdate(data))).toBe(true);
});

it.each([
  { allowed_read_sections: null }, { allowed_write_sections: ["unknown"] }, { allowed_read_sections: ["profile"] },
  { allowed_write_tools: ["unreviewed_tool"] }, { allowed_write_tools: ["configure_group_link"] },
  { permission_revision: 0 }, { allowed_write_sections: ["exports", "exports"] },
  { section_catalog: [null] }, { write_tool_requirements: [{ name: "unknown", required_sections: ["unknown"] }] },
])("rejects malformed or unsupported saved authority %j without throwing", (values) => {
  expect(validPermissions(permissionFixture(values as Partial<ReturnType<typeof permissionFixture>>))).toBe(false);
});

it("requires complete, versioned device permission fields", () => {
  expect(validConnectionPermissions(connectionFixture())).toBe(true);
  expect(validConnectionPermissions(connectionFixture({ allowed_read_sections: ["menu"] }))).toBe(true);
  expect(validConnectionPermissions(connectionFixture({ permission_revision: undefined }))).toBe(false);
  expect(validConnectionPermissions(connectionFixture({ allowed_write_sections: ["exports", "exports"] }))).toBe(false);
});

it("does not present retained scopes as enabled device allowances", () => {
  expect(hasPermission([connectionFixture()], ["mcp:read"])).toBe(true);
  expect(hasPermission([connectionFixture()], ["mcp:export"])).toBe(false);
  expect(hasPermission([connectionFixture({ read_enabled: false, write_enabled: true })], ["mcp:read"])).toBe(false);
  expect(hasPermission([connectionFixture({ write_enabled: true })], ["mcp:export"])).toBe(true);
});

it("distinguishes unsupported actions from a supported section that an administrator can enable", () => {
  const sections = deviceWriteSections(permissionFixture());
  expect(sections.find((section) => section.id === "profile")).toMatchObject({ write_supported: false, write_description: "No available write actions." });
  expect(sections.find((section) => section.id === "menu")).toMatchObject({ write_supported: true, write_allowed_by_settings: false,
    write_description: expect.stringContaining("turned off in global Write settings") });
  expect(sections.find((section) => section.id === "all_groups")).toMatchObject({ write_supported: true, write_allowed_by_settings: true });
});
