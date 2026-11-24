import Link from "next/link";
import { Check, Copy, UploadCloud } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ImageUploadField } from "@/features/branding/components/image-upload-field";
import type { CreateUploadLinkState } from "./use-create-upload-link-form";

export function CreateUploadLinkResult({ state }: { state: CreateUploadLinkState }) {
  const {
    createdImportGroupId,
    handleClose,
    generatedTargets,
    copyTarget,
    copiedTargetKey,
    actionError,
    bannerRetryGroupId,
    banner,
    setBanner,
    isPending,
    savingBanner,
    retryBanner
  } = state;
  return (<div className="space-y-6">
    <div role="status" className="rounded-lg border border-green-100 bg-green-50 p-4 text-sm text-green-800">
      {createdImportGroupId
        ? "Your group is ready. Open the group and choose Import Excel to upload your final passenger list."
        : "Success. The public client link is ready for sharing."}
    </div>

    {createdImportGroupId && (
      <Link
        href={`/passports/groups/${createdImportGroupId}`}
        className={`${buttonVariants()} w-full`}
        onClick={handleClose}
      >
        <UploadCloud className="h-4 w-4" aria-hidden="true" />
        Open group to import Excel
      </Link>
    )}

    <div className="space-y-4">
      {generatedTargets.map((target) => (
        <div key={target.key} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-900">{target.label} Link</div>
              <div className="text-xs text-slate-500">{target.description}</div>
            </div>
            <Button
              type="button"
              onClick={() => copyTarget(target)}
              variant="secondary"
              className="min-w-28"
            >
              {copiedTargetKey === target.key ? (
                <>
                  <Check className="h-4 w-4 text-green-600" /> Copied
                </>
              ) : (
                <>
                  <Copy className="h-4 w-4 text-slate-600" /> Copy
                </>
              )}
            </Button>
          </div>
          <Input
            readOnly
            value={target.url}
            aria-label={`${target.label} upload link`}
            className="bg-white"
          />
        </div>
      ))}
    </div>

    {actionError && (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {actionError}
      </div>
    )}

    {bannerRetryGroupId && <div className="space-y-3">
      <ImageUploadField kind="banner" value={banner} onChange={setBanner} disabled={isPending} />
      <Button
        type="button"
        variant="secondary"
        isLoading={savingBanner}
        disabled={banner === undefined}
        onClick={retryBanner}
      >Retry banner upload</Button>
    </div>}

    <Button onClick={handleClose} className="w-full">
      Done
    </Button>
  </div>);
}
