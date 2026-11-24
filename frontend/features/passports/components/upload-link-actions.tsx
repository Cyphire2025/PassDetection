import Link from "next/link";
import { Archive, Check, Copy, Pencil, RotateCcw, Trash2, UploadCloud, XCircle } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { getPassportUploadTargets } from "@/lib/utils/public-url";
import type { UploadLinkResponse } from "../api/upload-links.api";
import type { UploadLinkTableProps } from "./upload-link-table";

type Props = Pick<UploadLinkTableProps, "copiedLinkKey" | "onCopy" | "onClose" | "onOpen" | "onArchive" | "onRestore" | "onRename" | "onPermanentDelete" | "canPermanentlyDelete" | "isMutating"> & { link: UploadLinkResponse; align: "start" | "end" };

export function UploadLinkActions({
  link,
  align,
  copiedLinkKey,
  onCopy,
  onClose,
  onOpen,
  onArchive,
  onRestore,
  onRename,
  onPermanentDelete,
  canPermanentlyDelete,
  isMutating
}: Props) {
  const uploadTargets = link.import_only ? [] : getPassportUploadTargets(link.token);
  return (
    <div
      className={`flex flex-wrap items-center gap-2 ${align === "end" ? "justify-end" : "justify-start"
        }`}

    >
      {link.status === "active" && uploadTargets.map((target) => {
        const copyStateKey = `${link.id}:${target.key}`;
        return (
          <Button
            key={target.key}
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onCopy(link.id, target.key, target.url)}
            aria-label={`Copy ${target.label.toLowerCase()} upload link for ${link.name}`}

          >
            {copiedLinkKey === copyStateKey ? (
              <><Check className="h-3.5 w-3.5 text-green-600" /> Copied</>
            ) : (
              <><Copy className="h-3.5 w-3.5" /> {target.label}</>
            )}
          </Button>
        );
      })}
      {link.import_only && link.status !== "archived" && (
        <Link
          href={`/passports/groups/${link.id}`}
          className={buttonVariants({ variant: "secondary", size: "sm" })}
          aria-label={`Open ${link.name} to import Excel`}
        >
          <UploadCloud className="h-3.5 w-3.5" aria-hidden="true" /> Import Excel
        </Link>
      )}
      {!link.import_only && link.status === "active" && onClose && (
        <Button type="button" variant="outline" size="sm" onClick={() => onClose(link.id)} disabled={isMutating}>
          <XCircle className="h-3.5 w-3.5" /> Close
        </Button>
      )}
      {!link.import_only && link.status === "closed" && onOpen && (
        <Button type="button" variant="outline" size="sm" onClick={() => onOpen(link.id)} disabled={isMutating}>
          <RotateCcw className="h-3.5 w-3.5" /> Open
        </Button>
      )}
      {onRename && (
        <Button type="button" variant="secondary" size="sm" onClick={() => onRename(link)} disabled={isMutating}>
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      )}
      {link.status !== "archived" && onArchive && (
        <Button type="button" variant="ghost" size="sm" onClick={() => onArchive(link.id)} disabled={isMutating}>
          <Archive className="h-3.5 w-3.5" /> Archive
        </Button>
      )}
      {link.status === "archived" && onRestore && (
        <Button type="button" variant="secondary" size="sm" onClick={() => onRestore(link.id)} disabled={isMutating}>
          <RotateCcw className="h-3.5 w-3.5" /> Restore
        </Button>
      )}
      {canPermanentlyDelete && link.status === "archived" && onPermanentDelete && (
        <Button type="button" variant="danger" size="sm" onClick={() => onPermanentDelete(link.id)} disabled={isMutating}>
          <Trash2 className="h-3.5 w-3.5" /> Delete
        </Button>
      )}
    </div>
  );
}
