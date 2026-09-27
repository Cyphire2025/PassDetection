"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import Image from "next/image";
import { ArrowLeft, ImagePlus, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PASSPORT_UPLOAD_PAGES, type PassportUploadPage, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { passportBundleError } from "../services/configured-upload";
import { errorMessage, formatFileSize } from "../services/upload-flow-helpers";
import { preparePublicUploadFile, publicUploadFileError } from "../services/public-upload-file";
import { PASSPORT_IMAGE_ACCEPT } from "./upload-flow.constants";
import type { PassportDocumentBundle } from "./upload-flow.types";
import { InstructionLanguageSelector } from "./instruction-language-selector";
import type { InstructionLanguageControl } from "../hooks/use-instruction-language";
import { UPLOAD_INSTRUCTIONS } from "../config/instruction-translations";

// Keep the validated display copy while the original selected File is retained
// in the bundle for authoritative validation when the documents are submitted.
const preparedPreviews = new WeakMap<File, File>();
type PendingPage = { controller: AbortController; original: File | null };

interface PassportUploadPageProps {
  bundle: PassportDocumentBundle;
  config: UploadConfiguration;
  onChange: Dispatch<SetStateAction<PassportDocumentBundle>>;
  onContinue: () => void;
  onBack: () => void;
  error: string | null;
  instructions?: InstructionLanguageControl;
  token?: string;
  uploadSessionId?: string;
}

export function PassportUploadPage(props: PassportUploadPageProps) {
  const contextKey = `${props.token ?? ""}:${props.uploadSessionId ?? ""}:${props.config.passport_upload_pages.join(",")}`;
  return <PassportUploadPageContent key={contextKey} {...props} />;
}

function PassportUploadPageContent({ bundle, config, onChange, onContinue, onBack, error, instructions, token, uploadSessionId }: PassportUploadPageProps) {
  const language = instructions?.language ?? "en";
  const copy = UPLOAD_INSTRUCTIONS[language];
  const direction = language === "ur" ? "rtl" : "ltr";
  const [fileErrors, setFileErrors] = useState<Partial<Record<PassportUploadPage, string | null>>>({});
  const [preparing, setPreparing] = useState<Partial<Record<PassportUploadPage, File>>>({});
  const pendingRef = useRef(new Map<PassportUploadPage, PendingPage>());
  const bundleRef = useRef(bundle);
  const selectedPages = PASSPORT_UPLOAD_PAGES.filter((page) => config.passport_upload_pages.includes(page.id));

  useEffect(() => {
    const pending = pendingRef.current;
    return () => {
      pending.forEach(({ controller }) => controller.abort());
      pending.clear();
    };
  }, []);

  useEffect(() => {
    const previous = bundleRef.current;
    bundleRef.current = bundle;
    const reset = previous !== bundle && PASSPORT_UPLOAD_PAGES.every(({ id }) => !bundle[id]);
    for (const [page, pending] of pendingRef.current) {
      if (reset || bundle[page] !== pending.original) {
        pending.controller.abort();
        pendingRef.current.delete(page);
        setPreparing((current) => { const next = { ...current }; delete next[page]; return next; });
      }
    }
  }, [bundle]);

  const updateFile = async (page: PassportUploadPage, file: File | null) => {
    pendingRef.current.get(page)?.controller.abort();
    pendingRef.current.delete(page);
    setPreparing((current) => { const next = { ...current }; delete next[page]; return next; });
    const validationError = file ? publicUploadFileError(file, "passport") : null;
    setFileErrors((current) => ({ ...current, [page]: validationError }));
    if (validationError) return;
    if (!file) {
      onChange((current) => ({ ...current, [page]: null,
        ...(page === "front" || page === "back" ? { [`${page}Source`]: null, [`${page}ManuallyCropped`]: false } : {}),
      }));
      return;
    }
    const pending: PendingPage = { controller: new AbortController(), original: bundleRef.current[page] };
    pendingRef.current.set(page, pending);
    setPreparing((current) => ({ ...current, [page]: file }));
    try {
      const prepared = await preparePublicUploadFile(file, { token: token ?? "", uploadSessionId: uploadSessionId ?? "", purpose: "passport", signal: pending.controller.signal });
      if (pending.controller.signal.aborted || pendingRef.current.get(page) !== pending || bundleRef.current[page] !== pending.original) return;
      preparedPreviews.set(file, prepared);
      pendingRef.current.delete(page);
      onChange((current) => current[page] !== pending.original ? current : ({ ...current, [page]: file,
        ...(page === "front" || page === "back" ? { [`${page}Source`]: "file", [`${page}ManuallyCropped`]: false } : {}),
      }));
    } catch (prepareError) {
      if (!pending.controller.signal.aborted && pendingRef.current.get(page) === pending) {
        setFileErrors((current) => ({ ...current, [page]: errorMessage(prepareError, "This passport file could not be prepared. Please choose another file.") }));
      }
    } finally {
      if (pendingRef.current.get(page) === pending) pendingRef.current.delete(page);
      if (!pending.controller.signal.aborted) {
        setPreparing((current) => current[page] !== file ? current : (() => { const next = { ...current }; delete next[page]; return next; })());
      }
    }
  };
  const isPreparing = Object.keys(preparing).length > 0;
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-10">
      <div className="mx-auto max-w-3xl">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onBack} className="-ml-3"><ArrowLeft className="h-4 w-4" />Back to document options</Button>
          <InstructionLanguageSelector instructions={instructions} />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Upload Passport Pages</h1>
        <p lang={language} dir={direction} className="mt-2 text-sm leading-6 text-slate-600">{copy.passportIntro}</p>
        {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</p>}
        <div className="mt-6 space-y-4">
          {selectedPages.map((page, index) => {
            const file = bundle[page.id];
            const pendingFile = preparing[page.id];
            return (
              <section key={page.id} aria-labelledby={`passport-upload-${page.id}-heading`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 id={`passport-upload-${page.id}-heading`} className="text-base font-semibold text-slate-900">{index + 1}. {page.label}</h2>
                <p lang={language} dir={direction} className="mt-1 text-sm leading-6 text-slate-500">{copy[page.id]}</p>
                <div className="mt-4 grid items-start gap-5 sm:grid-cols-[220px_1fr]">
                  <div><PassportPageSample page={page.id} /><p className="mt-1 text-center text-xs text-slate-400">Illustrative sample only</p></div>
                  <div role="group" aria-label={`${page.label} upload`} aria-busy={Boolean(pendingFile)} className="min-w-0 space-y-3 rounded-2xl border border-blue-200 bg-blue-50/30 p-3 sm:p-4">
                    {pendingFile ? (
                      <div role="status" className="flex min-h-[180px] flex-col items-center justify-center gap-3 px-3 text-center text-sm text-slate-600">
                        <Loader2 className="h-7 w-7 animate-spin text-blue-700" aria-hidden="true" />
                        <p>Checking file and preparing preview…</p>
                        <p className="max-w-full truncate text-xs" title={pendingFile.name}>{pendingFile.name}</p>
                      </div>
                    ) : file ? <SelectedPassportPreview file={preparedPreviews.get(file) ?? file} original={file} label={page.label} /> : (
                      <div className="flex min-h-[140px] flex-col items-center justify-center gap-3 px-3 text-center">
                        <ImagePlus className="h-9 w-9 text-blue-500" aria-hidden="true" />
                        <p className="text-sm leading-6 text-slate-500">Your selected image or PDF page will appear here.</p>
                      </div>
                    )}
                    <label className="relative flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-800 focus-within:ring-2 focus-within:ring-blue-600">
                      <ImagePlus className="h-4 w-4 shrink-0" />{file || pendingFile ? "Replace file" : "Choose image or PDF"}
                      <input type="file" className="sr-only" accept={PASSPORT_IMAGE_ACCEPT} aria-label={`Upload ${page.label}`} onClick={(event) => { event.currentTarget.value = ""; }} onChange={(event) => { const selected = event.target.files?.[0]; if (selected) void updateFile(page.id, selected); }} />
                    </label>
                    {(file || pendingFile) && <Button type="button" variant="ghost" onClick={() => void updateFile(page.id, null)} className="h-auto min-h-9 w-full whitespace-normal text-red-700"><Trash2 className="h-4 w-4 shrink-0" />Remove {page.label.toLowerCase()}</Button>}
                    {fileErrors[page.id] && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-800">{fileErrors[page.id]}</p>}
                    <p className="text-xs leading-5 text-slate-500">JPEG/JPG, PNG, HEIC/HEIF, AVIF or PDF · Maximum 2 MB per file. PDFs must contain exactly 1 page.</p>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
        <Button className="mt-6 h-12 w-full" onClick={onContinue} disabled={isPreparing || Boolean(passportBundleError(bundle, config, "file"))}>Save passport pages and continue</Button>
      </div>
    </main>
  );
}

function SelectedPassportPreview({ file, original, label }: { file: File; original: File; label: string }) {
  const imageRef = useRef<HTMLImageElement>(null);
  const [failed, setFailed] = useState<File | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    if (imageRef.current) imageRef.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return <div>
    {failed !== file ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img ref={imageRef} alt={`Selected ${label}`} onError={() => setFailed(file)} className="mx-auto h-[180px] w-full max-w-[280px] rounded-lg bg-white object-contain" />
    ) : <p className="py-8 text-center text-sm text-slate-600">{failed === file ? "The preview could not be displayed. Please choose the file again." : "Preparing preview…"}</p>}
    <p className="mt-2 truncate text-sm font-medium text-slate-800" title={original.name}>{original.name}</p>
    <p className="text-xs text-slate-500">{formatFileSize(original.size)}</p>
  </div>;
}

export function PassportPageSample({ page }: { page: PassportUploadPage }) {
  const isCover = page === "cover" || page === "back_cover";
  if (isCover) {
    const isFrontCover = page === "cover";
    return <Image
      src={isFrontCover ? "/assets/upload-samples/passport-front-cover.png" : "/assets/upload-samples/passport-back-cover.png"}
      alt={`Passport ${isFrontCover ? "front" : "back"} cover sample`}
      width={isFrontCover ? 964 : 1005}
      height={isFrontCover ? 1292 : 1291}
      sizes="220px"
      className="h-[160px] w-full rounded-xl bg-slate-50 object-contain"
    />;
  }
  // The previous artwork is retained in passport-detail-samples-original.tsx.
  const isPersonalDetails = page === "front";
  return <Image
    src={isPersonalDetails ? "/assets/upload-samples/indian-passport-personal-details.svg" : "/assets/upload-samples/indian-passport-address-details.svg"}
    alt={`Illustrative Indian passport ${isPersonalDetails ? "personal details" : "address and family details"} page — sample only`}
    width={880}
    height={600}
    unoptimized
    className="h-[160px] w-full rounded-xl bg-slate-50 object-contain"
  />;
}
