import { Camera, ImagePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { NameInput } from "./upload-flow-fields";
import { PassportDocumentBundlePanel, PassportUploadSection } from "./upload-flow-passport-picker";
import type { FlowMode, PassportDocumentBundle } from "./upload-flow.types";

export function UploadDocumentOptions({
  config, allowFilesFromDevice, flowMode, clientName, onClientName,
  passportMethod, bundle, onBundleChange, onScan, onFileSelect, onUpload, onOpenUpload, onSkip,
}: {
  config: UploadConfiguration;
  allowFilesFromDevice: boolean;
  flowMode: FlowMode | null;
  clientName: string;
  onClientName: (value: string) => void;
  passportMethod: "camera" | "file";
  bundle: PassportDocumentBundle;
  onBundleChange: (bundle: PassportDocumentBundle) => void;
  onScan: (page: "front" | "back") => void;
  onFileSelect: (page: "front" | "back", file: File) => void;
  onUpload: () => void;
  onOpenUpload: () => void;
  onSkip: () => void;
}) {
  const passportRequired = config.passport_enabled && config.passport_required;
  const requestName = flowMode !== "family" && (!passportRequired || !config.passport_upload_pages.includes("front"));
  return <>
    {requestName && <label className="block space-y-2 text-sm font-medium text-slate-700">
      Full name <span aria-hidden="true">*</span>
      <NameInput value={clientName} onChange={onClientName} placeholder="Full name as shown on your travel documents" />
    </label>}
    {config.passport_enabled && <PassportUploadSection allowFilesFromDevice={allowFilesFromDevice} allowLiveScan={config.passport_live_scan} required={passportRequired}>
      <div className="grid gap-3 sm:grid-cols-2">
        {config.passport_live_scan && <Button type="button" variant="outline" onClick={() => onScan("front")} className="h-12"><Camera className="h-4 w-4" />Live scan</Button>}
        {allowFilesFromDevice && <Button type="button" variant="outline" onClick={onOpenUpload} className="h-12"><ImagePlus className="h-4 w-4" />Upload passport images</Button>}
      </div>
      {passportMethod === "camera" && (bundle.front || bundle.back) && <PassportDocumentBundlePanel bundle={bundle} allowFilesFromDevice={false} onChange={onBundleChange} onScan={onScan} onFileSelect={onFileSelect} onUpload={onUpload} />}
    </PassportUploadSection>}
    {!passportRequired && <Button type="button" className="h-12 w-full" onClick={onSkip}>{config.passport_enabled ? "Continue without passport" : "Continue to your details"}</Button>}
  </>;
}
