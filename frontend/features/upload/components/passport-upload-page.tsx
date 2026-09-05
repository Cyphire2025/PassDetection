"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ImagePlus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PASSPORT_UPLOAD_PAGES, type PassportUploadPage, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { passportBundleError, passportUploadFileError } from "../services/configured-upload";
import { formatFileSize } from "../services/upload-flow-helpers";
import { PASSPORT_IMAGE_ACCEPT } from "./upload-flow.constants";
import type { PassportDocumentBundle } from "./upload-flow.types";

export function PassportUploadPage({ bundle, config, onChange, onContinue, onBack, error }: {
  bundle: PassportDocumentBundle;
  config: UploadConfiguration;
  onChange: (bundle: PassportDocumentBundle) => void;
  onContinue: () => void;
  onBack: () => void;
  error: string | null;
}) {
  const [fileError, setFileError] = useState<string | null>(null);
  const selectedPages = PASSPORT_UPLOAD_PAGES.filter((page) => config.passport_upload_pages.includes(page.id));
  const updateFile = (page: PassportUploadPage, file: File | null) => {
    const validationError = file ? passportUploadFileError(file) : null;
    setFileError(validationError);
    if (validationError) return;
    onChange({ ...bundle, [page]: file,
      ...(page === "front" || page === "back" ? { [`${page}Source`]: file ? "file" : null, [`${page}ManuallyCropped`]: false } : {}),
    });
  };
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-10">
      <div className="mx-auto max-w-3xl">
        <Button variant="ghost" onClick={onBack} className="mb-5 -ml-3"><ArrowLeft className="h-4 w-4" />Back to document options</Button>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Upload Passport Pages</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">Use the samples to identify each requested page. Include the complete page with clear, readable details. Each image must be 2 MB or smaller.</p>
        {(fileError || error) && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{fileError || error}</p>}
        <div className="mt-6 space-y-4">
          {selectedPages.map((page, index) => (
            <section key={page.id} aria-labelledby={`passport-upload-${page.id}-heading`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 id={`passport-upload-${page.id}-heading`} className="text-base font-semibold text-slate-900">{index + 1}. {page.label}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">{page.description}</p>
              <div className="mt-4 grid items-start gap-5 sm:grid-cols-[220px_1fr]">
                <div><PassportPageSample page={page.id} /><p className="mt-1 text-center text-xs text-slate-400">Illustrative sample only</p></div>
                <div className="min-w-0 space-y-3">
                  {bundle[page.id] && <SelectedPassportPreview file={bundle[page.id]!} label={page.label} />}
                  <label className="relative flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 text-sm font-semibold text-blue-800 focus-within:ring-2 focus-within:ring-blue-600">
                    <ImagePlus className="h-4 w-4" />{bundle[page.id] ? "Replace image" : "Upload image"}
                    <input type="file" className="sr-only" accept={PASSPORT_IMAGE_ACCEPT} aria-label={`Upload ${page.label}`} onClick={(event) => { event.currentTarget.value = ""; }} onChange={(event) => { const file = event.target.files?.[0]; if (file) updateFile(page.id, file); }} />
                  </label>
                  {bundle[page.id] && <Button type="button" variant="ghost" onClick={() => updateFile(page.id, null)} className="h-9 w-full text-red-700"><Trash2 className="h-4 w-4" />Remove {page.label.toLowerCase()}</Button>}
                  <p className="text-xs leading-5 text-slate-500">JPG, PNG, WebP, HEIC/HEIF, AVIF, BMP or TIFF · Maximum 2 MB per image</p>
                </div>
              </div>
            </section>
          ))}
        </div>
        <Button className="mt-6 h-12 w-full" onClick={onContinue} disabled={Boolean(passportBundleError(bundle, config, "file"))}>Save passport pages and continue</Button>
      </div>
    </main>
  );
}

function SelectedPassportPreview({ file, label }: { file: File; label: string }) {
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);
  const [failed, setFailed] = useState<File | null>(null);
  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    const display = (blob: Blob) => {
      if (cancelled) return;
      const url = URL.createObjectURL(blob);
      urls.push(url);
      setPreview({ file, url });
    };
    void Promise.resolve().then(async () => {
      // Use a small display copy when the browser can decode the source. The
      // selected upload remains the original file with its validated size.
      if (typeof createImageBitmap === "function") {
        let bitmap: ImageBitmap | null = null;
        try {
          bitmap = await createImageBitmap(file);
          const scale = Math.min(1, 560 / Math.max(bitmap.width, bitmap.height));
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(bitmap.width * scale));
          canvas.height = Math.max(1, Math.round(bitmap.height * scale));
          const context = canvas.getContext("2d");
          if (context) {
            context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
            const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
            if (blob) { display(blob); return; }
          }
        } catch { /* Some formats can still be decoded by the native image element. */ }
        finally { bitmap?.close(); }
      }
      display(file);
    });
    return () => { cancelled = true; urls.forEach((url) => URL.revokeObjectURL(url)); };
  }, [file]);
  return <div className="rounded-xl border border-emerald-200 bg-emerald-50/30 p-3">
    {preview?.file === file && failed !== file ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={preview.url} alt={`Selected ${label}`} onError={() => setFailed(file)} className="mx-auto h-[180px] w-full max-w-[280px] rounded-lg bg-white object-contain" />
    ) : <p className="py-8 text-center text-sm text-slate-600">{failed === file ? "Your browser cannot preview this image format. Choose JPG or PNG for an immediate preview, or continue with the selected image." : "Preparing image preview…"}</p>}
    <p className="mt-2 truncate text-sm font-medium text-slate-800" title={file.name}>{file.name}</p>
    <p className="text-xs text-slate-500">{formatFileSize(file.size)}</p>
  </div>;
}

export function PassportPageSample({ page }: { page: PassportUploadPage }) {
  const isCover = page === "cover" || page === "back_cover";
  return <svg role="img" aria-label={`Illustration of ${PASSPORT_UPLOAD_PAGES.find((item) => item.id === page)?.label}`} viewBox="0 0 220 160" className="h-[160px] w-full rounded-xl bg-slate-50">
    {isCover ? <>
      <rect x="62" y="7" width="96" height="145" rx="6" fill="#192d4b" stroke="#0f172a" />
      <rect x="66" y="11" width="88" height="137" rx="4" fill="none" stroke="#af9354" opacity="0.7" />
      {page === "cover" && <><text x="110" y="43" textAnchor="middle" fontSize="10" fill="#dfc783" fontFamily="sans-serif">PASSPORT</text><circle cx="110" cy="81" r="17" fill="none" stroke="#dfc783" /><path d="M93 81h34M110 64v34M101 66q-10 15 0 30M119 66q10 15 0 30" fill="none" stroke="#dfc783" /></>}
    </> : <>
      <rect x="9" y="18" width="202" height="123" rx="5" fill="#eef3ea" stroke="#b9c6b6" />
      <text x="24" y="37" fill="#52634d" fontFamily="sans-serif" fontSize="8">{page === "front" ? "PERSONAL DETAILS" : "ADDRESS AND OTHER PARTICULARS"}</text>
      {page === "front" ? <><rect x="22" y="47" width="46" height="56" rx="3" fill="#cbd5e1" /><circle cx="45" cy="63" r="8" fill="#94a3b8" /><path d="M29 94q2-22 16-22t16 22" fill="#94a3b8" />{[52,66,80,94].map((y) => <rect key={y} x="81" y={y} width={y % 3 ? 108 : 71} height="4" rx="2" fill="#a4b3a0" />)}<text x="22" y="119" fill="#72826c" fontSize="8" fontFamily="monospace">P&lt;SAMPLE&lt;PERSON&lt;&lt;&lt;&lt;&lt;&lt;&lt;</text><text x="22" y="130" fill="#72826c" fontSize="8" fontFamily="monospace">000000000&lt;&lt;&lt;0000000&lt;&lt;&lt;</text></> : [52,65,78,91,104,117].map((y) => <rect key={y} x="24" y={y} width={y % 2 ? 154 : 125} height="4" rx="2" fill="#a4b3a0" />)}
    </>}
    <text x="110" y="91" textAnchor="middle" transform="rotate(-16 110 80)" fill={isCover ? "#e4d096" : "#607268"} opacity="0.5" fontWeight="bold" fontSize="20" fontFamily="sans-serif">SAMPLE</text>
  </svg>;
}
