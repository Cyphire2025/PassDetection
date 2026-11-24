"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button, Input } from "@/components/ui";
import type { CommonDocumentUpload, GcCommonDocument, GcDocumentCategory } from "../types";
import { gcAppErrorMessage } from "../utils";
import { GcSelect } from "./gc-select";

export function DocumentUploadForm({
  id,
  categories,
  fixedCategory,
  fixedTitle,
  replaceDocument,
  isUploading,
  onUpload,
  onComplete,
  onError,
}: {
  id: string;
  categories?: { value: GcDocumentCategory; label: string }[];
  fixedCategory?: GcDocumentCategory;
  fixedTitle?: string;
  replaceDocument: GcCommonDocument | null;
  isUploading: boolean;
  onUpload: (upload: CommonDocumentUpload) => Promise<void>;
  onComplete: () => void;
  onError: (message: string | null) => void;
}) {
  const uploadInFlight = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState(replaceDocument?.title ?? fixedTitle ?? "");
  const [category, setCategory] = useState<GcDocumentCategory>(
    fixedCategory ?? replaceDocument?.category ?? categories?.[0]?.value ?? "other",
  );
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const upload = async () => {
    if (uploadInFlight.current) return;
    onError(null);
    const normalizedTitle = (fixedTitle ?? title).trim();
    if (!file || !normalizedTitle) {
      onError("Choose a PDF and enter a document title.");
      return;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      onError("Only PDF common documents are accepted.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      onError("The PDF exceeds the 25 MB dashboard upload limit.");
      return;
    }
    uploadInFlight.current = true;
    try {
      setUploadProgress(0);
      await onUpload({
        file,
        title: normalizedTitle,
        category: fixedCategory ?? category,
        replace_document_id: replaceDocument?.id,
        onProgress: setUploadProgress,
      });
      setFile(null);
      setFileInputKey((value) => value + 1);
      if (!fixedTitle) setTitle("");
      onComplete();
    } catch (uploadError) {
      onError(gcAppErrorMessage(uploadError, "The common document could not be uploaded."));
    } finally {
      uploadInFlight.current = false;
      setUploadProgress(null);
    }
  };

  return (
    <div id={id} className="scroll-mt-24 space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div>
        <h4 className="font-semibold text-slate-900">{replaceDocument ? `Upload a new version of ${replaceDocument.title}` : fixedTitle ? `Upload ${fixedTitle} PDF` : "Upload common document"}</h4>
        <p className="mt-1 text-xs text-slate-500">The file remains a draft until you publish it.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {fixedTitle ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Document title</span>
            <span className="flex h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800">{fixedTitle}</span>
          </div>
        ) : (
          <Input label="Document title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        )}
        {fixedCategory ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Category</span>
            <span className="flex h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800">Itinerary PDF</span>
          </div>
        ) : (
          <GcSelect
            id={`${id}-category`}
            label="Category"
            value={category}
            options={categories ?? []}
            onChange={(nextCategory) => setCategory(nextCategory as GcDocumentCategory)}
          />
        )}
      </div>
      <label className="relative flex min-h-24 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border border-dashed border-slate-300 bg-white px-4 py-5 text-center hover:border-blue-400 hover:bg-blue-50/40 focus-within:ring-2 focus-within:ring-blue-600">
        <Upload className="h-5 w-5 text-slate-400" aria-hidden="true" />
        <span className="mt-2 text-sm font-medium text-slate-700">{file ? file.name : "Choose PDF"}</span>
        <span className="mt-1 text-xs text-slate-500">PDF only, up to 25 MB</span>
        <input
          key={fileInputKey}
          type="file"
          accept="application/pdf,.pdf"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          onChange={(event) => {
            const nextFile = event.target.files?.[0] ?? null;
            setFile(nextFile);
            if (nextFile && !fixedTitle && !title) setTitle(nextFile.name.replace(/\.pdf$/i, ""));
          }}
        />
      </label>
      {isUploading && uploadProgress !== null ? (
        <div
          className="space-y-2 rounded-xl border border-blue-100 bg-blue-50/70 p-3"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={uploadProgress}
          aria-label="Document upload progress"
        >
          <div className="flex items-center justify-between gap-3 text-xs font-medium text-blue-900">
            <span>{uploadProgress < 100 ? "Uploading PDF" : "Upload complete — checking and saving PDF"}</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-blue-100">
            <div
              className="h-full rounded-full bg-blue-600 transition-[width] duration-200 ease-out"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      ) : null}
      <div className="flex justify-end">
        <Button type="button" isLoading={isUploading} onClick={() => void upload()}>
          {isUploading && uploadProgress !== null
            ? uploadProgress < 100 ? `Uploading ${uploadProgress}%` : "Checking PDF"
            : replaceDocument ? "Upload replacement as draft" : "Upload as draft"}
        </Button>
      </div>
    </div>
  );
}

