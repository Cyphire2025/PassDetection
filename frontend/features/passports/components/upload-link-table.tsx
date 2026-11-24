import { Archive, CheckCircle2, Clock } from "lucide-react";
import type { UploadLinkResponse } from "../api/upload-links.api";
import { UploadLinkActions } from "./upload-link-actions";

export type UploadLinkTableProps = {
  caption: string;
  links: UploadLinkResponse[];
  copiedLinkKey: string | null;
  onCopy: (linkId: string, targetKey: string, url: string) => void;
  onClose?: (id: string) => void;
  onOpen?: (id: string) => void;
  onArchive?: (id: string) => void;
  onRestore?: (id: string) => void;
  onRename?: (link: UploadLinkResponse) => void;
  onPermanentDelete?: (id: string) => void;
  canPermanentlyDelete?: boolean;
  isMutating?: boolean;
  compact?: boolean;
};

export function UploadLinkTable({
  caption,
  links,
  copiedLinkKey,
  onCopy,
  onClose,
  onOpen,
  onArchive,
  onRestore,
  onRename,
  onPermanentDelete,
  canPermanentlyDelete = true,
  isMutating = false,
  compact = false,
}: UploadLinkTableProps) {
  const actionProps = { copiedLinkKey, onCopy, onClose, onOpen, onArchive, onRestore, onRename, onPermanentDelete, canPermanentlyDelete, isMutating };

  return (
    <div className={compact ? "" : "overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"}>
      <div className="divide-y divide-slate-100 md:hidden">
        {links.map((link) => (
          <article
            key={link.id}
            className="px-4 py-4"
            style={{ contentVisibility: "auto", containIntrinsicSize: "0 240px" }}

          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="font-semibold text-slate-950">{link.name}</h3>
                <CompanyAssignmentLabel group={link} />
                {link.import_only && <span className="mt-1 inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Excel import</span>}
                {link.destination && (
                  <p className="mt-1 truncate text-xs text-slate-500">{link.destination}</p>
                )}
              </div>
              <StatusPill status={link.status} />
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3 border-y border-slate-100 py-3 text-sm">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Created</dt>
                <dd className="mt-1 font-medium text-slate-800">
                  {new Date(link.created_at).toLocaleDateString()}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Closed</dt>
                <dd className="mt-1 font-medium text-slate-800">
                  {link.closed_at ? new Date(link.closed_at).toLocaleDateString() : "Not closed"}
                </dd>
              </div>
            </dl>
            <div className="mt-3">{<UploadLinkActions link={link} align="start" {...actionProps} />}</div>
          </article>
        ))}
      </div>

      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[980px] text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
            <tr>
              <th scope="col" className="px-5 py-3.5">Group Name</th>
              <th scope="col" className="px-5 py-3.5">Status</th>
              <th scope="col" className="px-5 py-3.5">Created</th>
              <th scope="col" className="px-5 py-3.5">Closed</th>
              <th scope="col" className="px-5 py-3.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {links.map((link) => (
              <tr key={link.id} className="transition-colors hover:bg-slate-50/50">
                <td className="px-6 py-4">
                  <div className="font-medium text-slate-900">{link.name}</div>
                  <CompanyAssignmentLabel group={link} />
                  {link.import_only && <span className="mt-1 inline-block rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Excel import</span>}
                </td>
                <td className="px-6 py-4"><StatusPill status={link.status} /></td>
                <td className="px-6 py-4 text-slate-600">{new Date(link.created_at).toLocaleDateString()}</td>
                <td className="px-6 py-4 text-slate-600">
                  {link.closed_at ? new Date(link.closed_at).toLocaleDateString() : "-"}
                </td>
                <td className="px-6 py-4">{<UploadLinkActions link={link} align="end" {...actionProps} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompanyAssignmentLabel({ group }: { group: UploadLinkResponse }) {
  return <p className="mt-1 break-words text-xs text-slate-500">{group.company?.name ?? "Company not assigned"}{group.company?.status === "inactive" ? " · Inactive" : ""}</p>;
}

function StatusPill({ status }: { status: UploadLinkResponse["status"] }) {
  if (status === "active") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700"
      >
        <Clock className="h-3.5 w-3.5" /> Active
      </span>
    );
  }
  if (status === "closed") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700"
      >
        <CheckCircle2 className="h-3.5 w-3.5" /> Closed
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500"
    >
      <Archive className="h-3.5 w-3.5" /> Archived
    </span>
  );
}
