"use client";

import { ROUTES } from "@/constants/routes";
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  FileText,
  History,
  MessageCircle,
  Send,
  Settings2,
  Users,
} from "lucide-react";
import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { Button, Skeleton } from "@/components/ui";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { useWhatsAppGroup } from "../hooks/use-whatsapp";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import styles from "./broadcast-workspace.module.css";

const BroadcastContext = createContext<WhatsAppBroadcastGroupDetail | null>(
  null,
);
export function useBroadcast() {
  const broadcast = useContext(BroadcastContext);
  if (!broadcast) throw new Error("A broadcast workspace is required.");
  return broadcast;
}

const sections = [
  { path: "", label: "Send messages", Icon: Send },
  { path: "/history", label: "Delivery history", Icon: History },
  { path: "/documents", label: "Documents", Icon: FileText },
  { path: "/recipients", label: "Recipients", Icon: Users },
  { path: "/details", label: "Broadcast details", Icon: Settings2 },
];

export function BroadcastWorkspaceShell({
  broadcastId,
  children,
}: {
  broadcastId: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const query = useWhatsAppGroup(broadcastId);
  const base = ROUTES.dashboard.whatsappBroadcast(broadcastId);
  if (query.error)
    return (
      <div className="space-y-4">
        <Link
          href={ROUTES.dashboard.whatsapp}
          className="inline-flex items-center gap-2 text-sm text-slate-500"
        >
          <ArrowLeft className="h-4 w-4" />
          All broadcasts
        </Link>
        <ErrorBanner
          message={readErrorMessage(
            query.error,
            "This broadcast could not be loaded.",
          )}
        />
        <Button variant="secondary" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </div>
    );
  if (!query.data)
    return (
      <div aria-label="Loading broadcast workspace" className="space-y-6">
        <Skeleton className="h-24" />
        <Skeleton className="h-12" />
        <Skeleton className="h-96" />
      </div>
    );
  const group = query.data;
  return (
    <BroadcastContext value={group}>
      <div className="min-w-0 space-y-6">
        <header>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Link
              href={ROUTES.dashboard.whatsapp}
              className="inline-flex items-center gap-1.5 hover:text-blue-700"
            >
              <MessageCircle className="h-3.5 w-3.5" />
              WhatsApp broadcasts
            </Link>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate text-slate-700">{group.name}</span>
          </div>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold tracking-tight text-slate-950">
                  {group.name}
                </h1>
                <span
                  className={`rounded-md px-2 py-1 text-xs font-medium ${group.is_archived ? "bg-slate-100 text-slate-500" : "bg-emerald-50 text-emerald-700"}`}
                >
                  {group.is_archived ? "Archived" : "Active broadcast"}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-500">
                {group.recipient_count.toLocaleString()} WhatsApp numbers
                <span className="mx-2 text-slate-300">·</span>
                {group.total_contact_count.toLocaleString()} contact records
              </p>
            </div>
            <Link
              href={ROUTES.dashboard.whatsapp}
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-slate-500 hover:bg-white hover:text-slate-900"
            >
              All broadcasts
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </header>
        <nav
          aria-label="Broadcast sections"
          className="flex gap-1 overflow-x-auto border-b border-slate-200"
        >
          {sections.map(({ path, label, Icon }) => {
            const active = pathname === base + path;
            return (
              <Link
                key={path}
                href={`${base}${path}` as Route}
                aria-current={active ? "page" : undefined}
                className={`inline-flex shrink-0 items-center gap-2 border-b-2 px-4 py-3.5 text-sm font-medium transition-colors focus-visible:outline-blue-500 ${active ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:bg-white/60 hover:text-slate-900"}`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </Link>
            );
          })}
        </nav>
        {group.is_archived && (
          <p
            role="status"
            className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600"
          >
            This broadcast is archived. You can browse its history, documents
            and recipients. Restore it in Broadcast details to make changes.
          </p>
        )}
        <div key={pathname} className={styles.enter}>
          {children}
        </div>
      </div>
    </BroadcastContext>
  );
}
