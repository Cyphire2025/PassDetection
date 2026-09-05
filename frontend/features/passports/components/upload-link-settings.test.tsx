import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  getUploadLinkSettings,
  getUploadLinkSettingsError,
  UploadLinkSettings,
  type UploadLinkSettingsValue,
} from "./upload-link-settings";

function Harness({ initial = {} }: { initial?: Partial<UploadLinkSettingsValue> }) {
  const [value, setValue] = useState(() => getUploadLinkSettings(initial));
  return (
    <>
      <UploadLinkSettings value={value} onChange={(patch) => setValue((current) => ({ ...current, ...patch }))} />
      <output data-testid="settings">{JSON.stringify(value)}</output>
    </>
  );
}

const readSettings = (): UploadLinkSettingsValue => JSON.parse(screen.getByTestId("settings").textContent || "{}");

describe("upload link settings", () => {
  it.each([undefined, null])("preserves legacy airport collection when configuration is %s", (upload_configuration) => {
    const settings = getUploadLinkSettings({
      upload_configuration,
      nearest_international_airport_enabled: false,
      departure_cities: ["Delhi", "Mumbai"],
    });
    expect(settings.nearest_international_airport_enabled).toBe(true);
    expect(settings.departure_cities).toEqual(["Delhi", "Mumbai"]);
    expect(getUploadLinkSettingsError(settings)).toBeUndefined();
    expect(getUploadLinkSettings({
      ...settings,
      nearest_international_airport_enabled: false,
    }).nearest_international_airport_enabled).toBe(false);
  });

  it("presents the requested sections in order and reveals enabled document methods", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual([
      "Visa Photo", "Passport", "Travel Preferences", "Professional Details", "Miscellaneous", "Custom questions", "Custom Detail",
    ]);
    expect(screen.queryByRole("switch", { name: /Live Photo Capture/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Enable Visa Photo" }));
    expect(screen.getByRole("switch", { name: "Disable Live Photo Capture" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Disable Photo Upload" })).toBeChecked();
    await user.click(screen.getByRole("switch", { name: "Disable Live Photo Capture" }));
    expect(readSettings().upload_configuration.visa_photo_live_capture).toBe(false);
    expect(readSettings().upload_configuration.visa_photo_upload).toBe(true);
    await user.click(screen.getByRole("checkbox", { name: "Make Visa Photo compulsory" }));
    expect(readSettings().upload_configuration.visa_photo_required).toBe(false);
    await user.click(screen.getByRole("switch", { name: "Disable Visa Photo" }));
    expect(screen.queryByRole("switch", { name: /Photo Upload/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Enable Visa Photo" }));
    expect(screen.getByRole("switch", { name: "Enable Live Photo Capture" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Make Visa Photo compulsory" })).not.toBeChecked();
  });

  it("defaults to both details pages and preserves cover selections when uploads are switched off", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText(/Pages to request/));
    expect(screen.getByRole("checkbox", { name: /^Personal Details Page/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Address Details Page/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Passport Front Cover/ })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: /^Passport Back Cover/ }));
    await user.click(screen.getByRole("checkbox", { name: /^Passport Front Cover/ }));
    expect(readSettings().upload_configuration.passport_upload_pages).toEqual(["cover", "back_cover", "front", "back"]);
    await user.click(screen.getByRole("switch", { name: "Disable Passport Document Upload" }));
    expect(screen.queryByText(/Pages to request/)).not.toBeInTheDocument();
    expect(readSettings().upload_configuration.passport_live_scan).toBe(true);
    await user.click(screen.getByRole("switch", { name: "Disable Passport" }));
    expect(screen.queryByRole("switch", { name: /Live Passport Scan/ })).not.toBeInTheDocument();
    expect(readSettings().upload_configuration.passport_upload_pages).toEqual(["cover", "back_cover", "front", "back"]);
  });

  it("allows professional labels to be edited while keeping Staff Code fixed", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("switch", { name: "Enable Agent/Employee Code" }));
    const codeLabel = screen.getByRole("textbox", { name: "Code field label" });
    expect(codeLabel).toHaveValue("Agent/Employee Code");
    await user.clear(codeLabel);
    await user.type(codeLabel, "Producer Code");
    await user.click(screen.getByRole("switch", { name: "Enable Agency/Dealership Name" }));
    const agencyLabel = screen.getByRole("textbox", { name: "Organisation field label" });
    await user.clear(agencyLabel);
    await user.type(agencyLabel, "Producer Company");
    await user.click(screen.getByRole("switch", { name: "Enable Staff Code" }));
    expect(readSettings().upload_configuration.agent_employee_code_label).toBe("Producer Code");
    expect(readSettings().upload_configuration.agency_dealership_name_label).toBe("Producer Company");
    expect(screen.queryByRole("textbox", { name: /Staff Code/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Agent or Employee/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Make Agent/Employee Code compulsory" }));
    expect(readSettings().upload_configuration.required_fields.agent_employee_code).toBe(false);
    expect(readSettings().staff_code_enabled).toBe(true);
  });

  it("keeps required decisions independent for legacy and new custom questions and details", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{
      custom_questions: [{ id: "55789cf1-e055-4cda-86c2-7c8d79d52072", label: "Excursion", enabled: true, options: ["Museum", "Beach"] }],
      custom_details: [{ id: "2823dd2e-b35e-4861-bc30-7f7b9d57d49b", label: "Membership", enabled: true }],
    }} />);
    expect(screen.getByRole("checkbox", { name: "Make Excursion compulsory" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Make Excursion compulsory" }));
    expect(screen.getByRole("checkbox", { name: "Make Membership compulsory" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Make Membership compulsory" }));
    await user.click(screen.getByRole("button", { name: "Add custom detail" }));
    expect(readSettings().custom_questions[0].required).toBe(false);
    expect(readSettings().custom_details[0].required).toBe(false);
    expect(readSettings().custom_details[1].required).toBe(true);
    await user.click(screen.getByRole("switch", { name: "Disable Membership" }));
    expect(screen.getByRole("checkbox", { name: "Make Membership compulsory" })).toBeDisabled();
  });

  it("rejects configurations that leave an enabled document section without a usable method", () => {
    const settings = getUploadLinkSettings({ require_selfie: true });
    settings.upload_configuration.visa_photo_live_capture = false;
    settings.upload_configuration.visa_photo_upload = false;
    expect(getUploadLinkSettingsError(settings)).toBe("Enable at least one method for Visa Photo.");
    settings.require_selfie = false;
    settings.allow_files_from_device = false;
    settings.upload_configuration.passport_live_scan = false;
    expect(getUploadLinkSettingsError(settings)).toBe("Enable at least one method for Passport.");
    settings.allow_files_from_device = true;
    settings.upload_configuration.passport_upload_pages = [];
    expect(getUploadLinkSettingsError(settings)).toBe("Select at least one passport page to upload.");
    settings.upload_configuration.passport_enabled = false;
    expect(getUploadLinkSettingsError(settings)).toBeUndefined();
  });
});
