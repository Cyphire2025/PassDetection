import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useVisaCamera } from "../hooks/use-visa-camera";
import type { VisaPhotoFinalValidation } from "./visa-selfie-quality";
import { VisaCameraFooter } from "./visa-camera-footer";

vi.mock("../hooks/use-visa-detector", () => ({ useVisaDetector: () => undefined }));
vi.mock("../hooks/use-visa-camera-stream", () => ({ useVisaCameraStream: () => undefined }));
vi.mock("../hooks/use-visa-live-analysis", () => ({ useVisaLiveAnalysis: () => undefined }));
afterEach(cleanup);
const file = new File(["synthetic"], "visa.jpg", { type: "image/jpeg" });
function Preview({ outcome, onCapture }: { outcome: VisaPhotoFinalValidation["outcome"]; onCapture: (file: File) => void }) {
  const camera = useVisaCamera({ onCapture, onCancel: vi.fn() });
  const { setCapturedFile, setCapturedPreview, setFinalValidation } = camera;
  useEffect(() => {
    setCapturedFile(file);
    setCapturedPreview("blob:synthetic");
    setFinalValidation({ outcome, message: "Synthetic validation result", faceCount: "one_face", facePlacement: "ready", clarity: null, background: null });
  }, [outcome, setCapturedFile, setCapturedPreview, setFinalValidation]);
  return <VisaCameraFooter camera={camera} />;
}
it("requires explicit confirmation before accepting a borderline photo", async () => {
  const accept = vi.fn();
  render(<Preview outcome="borderline" onCapture={accept} />);
  const use = await screen.findByRole("button", { name: "Use Visa Photo" });
  expect(use).toBeDisabled();
  fireEvent.click(use);
  expect(accept).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(use).toBeEnabled();
  fireEvent.click(use);
  expect(accept).toHaveBeenCalledExactlyOnceWith(file);
});
it("never exposes acceptance for a hard validation failure", async () => {
  render(<Preview outcome="hard_failure" onCapture={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic validation result");
  expect(screen.queryByRole("button", { name: "Use Visa Photo" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retake" })).toBeEnabled();
});
it("accepts a passing exact-JPEG result without a borderline checkbox", async () => {
  const accept = vi.fn();
  render(<Preview outcome="pass" onCapture={accept} />);
  fireEvent.click(await screen.findByRole("button", { name: "Use Visa Photo" }));
  expect(accept).toHaveBeenCalledExactlyOnceWith(file);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
