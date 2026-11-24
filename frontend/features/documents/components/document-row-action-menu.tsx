import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FileX2, MoreVertical, RefreshCw } from "lucide-react";
import type {
  DistributedDocument,
  DistributionDocumentType,
  DocumentPassengerReviewRow,
} from "@/types/document-distribution.types";
import { distributionDocumentUploadLabel } from "../config/document-distribution-lanes";

type DocumentRowActionMenuProps = {
  row: DocumentPassengerReviewRow;
  documents: DistributedDocument[];
  documentType: DistributionDocumentType;
  pending: boolean;
  onReupload: (file: File) => void;
  onManualUpload?: (row: DocumentPassengerReviewRow, mode: "add" | "replace") => void;
  onRemoveAssignment: (documentId: string) => void;
};

export function DocumentRowActionMenu({
  row,
  documents,
  documentType,
  pending,
  onReupload,
  onManualUpload,
  onRemoveAssignment,
}: DocumentRowActionMenuProps) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const anchorPositionRef = useRef<{ left: number; top: number } | null>(null);
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number; maxHeight: number }>({ left: 8, top: 8, maxHeight: 320 });
  const label = distributionDocumentUploadLabel(documentType);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus({ preventScroll: true });
    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)
        && !triggerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnMove = (event: Event) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      const bounds = triggerRef.current?.getBoundingClientRect();
      const anchor = anchorPositionRef.current;
      // A scroll queued while revealing the trigger can arrive after the menu
      // opens. Dismiss only when the anchor actually moves from its saved place.
      if (event.type === "resize" || !bounds || !anchor
        || Math.abs(bounds.left - anchor.left) > 0.5 || Math.abs(bounds.top - anchor.top) > 0.5) setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("scroll", closeOnMove, true);
    window.addEventListener("resize", closeOnMove);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("scroll", closeOnMove, true);
      window.removeEventListener("resize", closeOnMove);
    };
  }, [open]);

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
    }
    if (event.key === "Tab") setOpen(false);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? []);
      if (!items.length) return;
      event.preventDefault();
      const current = items.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
        : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next]?.focus();
    }
  };

  return (
    <div className="relative inline-flex justify-end">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.currentTarget.value = "";
          setOpen(false);
          if (file) onReupload(file);
        }}
      />
      <button
        ref={triggerRef}
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label={`${row.passenger_name} document actions`}
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={pending}
        onClick={() => {
          // Keep focus within an owning modal while escaping the scrolling table.
          setPortalContainer(triggerRef.current?.closest<HTMLElement>('[role="dialog"]') ?? document.body);
          const bounds = triggerRef.current?.getBoundingClientRect();
          if (bounds) {
            anchorPositionRef.current = { left: bounds.left, top: bounds.top };
            const availableBelow = window.innerHeight - bounds.bottom - 14;
            const above = availableBelow < 220 && bounds.top > availableBelow;
            const maxHeight = Math.min(320, Math.max(120, above ? bounds.top - 14 : availableBelow));
            setPosition({
              left: Math.max(8, Math.min(bounds.right - 288, window.innerWidth - 296)),
              ...(above ? { bottom: window.innerHeight - bounds.top + 6 } : { top: bounds.bottom + 6 }),
              maxHeight,
            });
          }
          setOpen((current) => !current);
        }}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && portalContainer && createPortal(
        <div ref={menuRef} role="menu" aria-label={`${row.passenger_name} document actions`} onKeyDown={handleMenuKeyDown} style={position} className="fixed z-[70] w-72 max-w-[calc(100vw-16px)] overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 text-left shadow-lg">
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            onClick={() => {
              if (onManualUpload) { setOpen(false); onManualUpload(row, documents.length ? "replace" : "add"); }
              else inputRef.current?.click();
            }}
          >
            <RefreshCw className="h-4 w-4" />
            {onManualUpload ? documents.length ? "Replace document" : "Upload document" : "Add another document"}
          </button>
          {onManualUpload && documents.length > 0 && <button type="button" role="menuitem" className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" onClick={() => { setOpen(false); onManualUpload(row, "add"); }}>
            <RefreshCw className="h-4 w-4" />Add another document
          </button>}
          {documents.length > 0 && <div className="my-1 border-t border-slate-100" />}
          {documents.map((document) => (
            <button
              key={document.id}
              type="button"
              role="menuitem"
              className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
              onClick={() => {
                setOpen(false);
                onRemoveAssignment(document.id);
              }}
            >
              <FileX2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">Remove assignment</span>
                <span className="block truncate text-xs text-slate-500" title={document.original_filename}>
                  {document.original_filename}
                </span>
              </span>
            </button>
          ))}
          <div className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            {onManualUpload ? `Assign a ${label} PDF directly to this passenger and save.` : `Upload one more ${label} PDF without removing saved documents.`}
          </div>
        </div>,
        portalContainer,
      )}
    </div>
  );
}
