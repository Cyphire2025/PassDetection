import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { INSTRUCTION_LANGUAGE_CODES } from "@/features/passports/types/instruction-language";
import { PassportUploadPage } from "./passport-upload-page";
import { VisaPhotoUpload } from "./visa-photo-upload";
import { useInstructionLanguage, availableInstructionLanguages } from "../hooks/use-instruction-language";
import { UPLOAD_INSTRUCTIONS } from "../config/instruction-translations";
import { VISA_PHOTO_GUIDELINES, VISA_PHOTO_GUIDELINE_IDS } from "../config/visa-photo-guidelines";
import { emptyDocumentBundle } from "../services/upload-flow-helpers";

const config: UploadConfiguration = { ...DEFAULT_UPLOAD_CONFIGURATION, instruction_languages_enabled: true, instruction_languages: ["mr", "hi", "ur"], passport_upload_pages: ["cover", "back_cover", "front", "back"] };

function Harness({ configuration = config, token = "link-one" }: { configuration?: UploadConfiguration; token?: string }) {
  const instructions = useInstructionLanguage(token, configuration);
  const [visa, setVisa] = useState(false);
  return <><button onClick={() => setVisa((value) => !value)}>Switch step</button>{visa
    ? <VisaPhotoUpload instructions={instructions} onCapture={() => {}} onCancel={() => {}} />
    : <PassportUploadPage config={configuration} instructions={instructions} bundle={emptyDocumentBundle()} onChange={() => {}} onContinue={() => {}} onBack={() => {}} error={null} />}</>;
}

beforeEach(() => sessionStorage.clear());

describe("configured instruction translations", () => {
  it("offers only configured languages after English and translates paragraphs across both steps", () => {
    render(<Harness />);
    expect(screen.getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual(["en", "mr", "hi", "ur"]);
    expect(screen.getByRole("combobox", { name: "Instruction language" })).toHaveValue("en");
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.en.passportIntro)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "mr" } });
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.mr.passportIntro)).toHaveAttribute("lang", "mr");
    for (const page of config.passport_upload_pages) expect(screen.getByText(UPLOAD_INSTRUCTIONS.mr[page])).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload Passport Pages" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "3. Personal Details Page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch step" }));
    expect(screen.getByRole("combobox")).toHaveValue("mr");
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.mr.visaWarning)).toBeInTheDocument();
    const guidelines = screen.getByRole("region", { name: VISA_PHOTO_GUIDELINES.mr.heading });
    expect(guidelines).toHaveAttribute("lang", "mr");
    for (const id of VISA_PHOTO_GUIDELINE_IDS) {
      expect(within(guidelines).getByRole("heading", { name: VISA_PHOTO_GUIDELINES.mr.items[id].title })).toBeInTheDocument();
      expect(within(guidelines).getByText(VISA_PHOTO_GUIDELINES.mr.items[id].description)).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "Upload Studio Visa Photo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Photograph sample" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose studio photo" })).toBeInTheDocument();
  });

  it("retains a link's choice after remount, isolates other links and falls back when languages change", () => {
    const first = render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "hi" } });
    first.unmount();
    const second = render(<Harness />);
    expect(screen.getByRole("combobox")).toHaveValue("hi");
    second.rerender(<Harness token="different-link" />);
    expect(screen.getByRole("combobox")).toHaveValue("en");
    second.rerender(<Harness configuration={{ ...config, instruction_languages: ["mr"] }} />);
    expect(screen.getByRole("combobox")).toHaveValue("en");
    second.rerender(<Harness configuration={{ ...config, instruction_languages_enabled: false }} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.en.passportIntro)).toBeInTheDocument();
  });

  it("sets Urdu direction only on translated text", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ur" } });
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.ur.passportIntro)).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("heading", { name: "Upload Passport Pages" }).closest('[dir="rtl"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Switch step" }));
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.ur.visaWarning)).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("region", { name: VISA_PHOTO_GUIDELINES.ur.heading })).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("heading", { name: "Upload Studio Visa Photo" }).closest('[dir="rtl"]')).toBeNull();
  });

  it("hides the selector for legacy settings and filters invalid persisted codes", () => {
    expect(availableInstructionLanguages(DEFAULT_UPLOAD_CONFIGURATION)).toEqual(["en"]);
    sessionStorage.setItem("passdetection:instruction-language:link-one", "invalid");
    render(<Harness />);
    expect(screen.getByRole("combobox")).toHaveValue("en");
  });

  it("keeps language selection usable when browser storage is unavailable", () => {
    const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage disabled"); });
    const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage disabled"); });
    try {
      render(<Harness />);
      fireEvent.change(screen.getByRole("combobox"), { target: { value: "hi" } });
      expect(screen.getByText(UPLOAD_INSTRUCTIONS.hi.passportIntro)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Switch step" }));
      expect(screen.getByRole("combobox")).toHaveValue("hi");
    } finally {
      read.mockRestore();
      write.mockRestore();
    }
  });

  it.each(INSTRUCTION_LANGUAGE_CODES)("has complete static %s copy with unchanged numeric requirements", (language) => {
    const translated = UPLOAD_INSTRUCTIONS[language];
    expect(Object.keys(translated)).toEqual(Object.keys(UPLOAD_INSTRUCTIONS.en));
    for (const key of Object.keys(translated) as (keyof typeof translated)[]) {
      expect(translated[key].length).toBeGreaterThan(10);
      expect(translated[key]).not.toBe(UPLOAD_INSTRUCTIONS.en[key]);
    }
    expect(translated.passportIntro).toContain("2 MB");
  });

  it.each(["en", ...INSTRUCTION_LANGUAGE_CODES] as const)("switches all six guideline headings and descriptions to %s", (language) => {
    render(<Harness configuration={{ ...config, instruction_languages: [...INSTRUCTION_LANGUAGE_CODES] }} />);
    fireEvent.click(screen.getByRole("button", { name: "Switch step" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: language } });
    const copy = VISA_PHOTO_GUIDELINES[language];
    const guidelines = screen.getByRole("region", { name: copy.heading });
    expect(guidelines).toHaveAttribute("lang", language);
    expect(guidelines).toHaveAttribute("dir", language === "ur" ? "rtl" : "ltr");
    expect(within(guidelines).getAllByRole("listitem")).toHaveLength(6);
    const uploadButton = screen.getByRole("button", { name: "Choose studio photo" });
    expect(guidelines.compareDocumentPosition(uploadButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const id of VISA_PHOTO_GUIDELINE_IDS) {
      expect(within(guidelines).getByRole("heading", { name: copy.items[id].title })).toBeInTheDocument();
      expect(within(guidelines).getByText(copy.items[id].description)).toBeInTheDocument();
      if (language !== "en") {
        expect(copy.items[id].title).not.toBe(VISA_PHOTO_GUIDELINES.en.items[id].title);
        expect(copy.items[id].description).not.toBe(VISA_PHOTO_GUIDELINES.en.items[id].description);
      }
    }
    expect(screen.queryByText("Face should fill approximately 70–80% of the photograph.")).not.toBeInTheDocument();
    expect(screen.queryByText("Plain white background. Face forward with your full head visible.")).not.toBeInTheDocument();
  });
});
