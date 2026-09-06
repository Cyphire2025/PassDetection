"use client";

import {
  ArrowRight,
  FilePenLine,
  FileStack,
  SendToBack,
  UsersRound,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";

const WORKFLOWS = [
  {
    title: "Rename Documents",
    description:
      "Upload visa and flight-ticket PDFs, review the detected details, and download renamed files.",
    href: ROUTES.dashboard.documentRename,
    icon: FilePenLine,
    action: "Prepare a PDF batch",
    accent: "border-cyan-200 bg-cyan-50/55 text-cyan-800",
    iconTone: "bg-cyan-100 text-cyan-700",
    steps: ["Upload mixed PDFs", "Review detected records", "Download renamed files"],
  },
  {
    title: "Document Distribution",
    description:
      "Match visas or flight tickets to passengers and save the reviewed list before sending.",
    href: ROUTES.dashboard.documentDistribution,
    icon: SendToBack,
    action: "Open distribution",
    accent: "border-blue-200 bg-blue-50/55 text-blue-900",
    iconTone: "bg-blue-100 text-blue-700",
    steps: ["Choose a document type", "Choose a group", "Review and distribute"],
  },
] as const;

export function DocumentHub() {
  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Documents"
        description="Rename supplier PDFs or match and distribute documents to passengers."
        icon={FileStack}
        accent="cyan"
      />

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="document-workflows-heading"
      >
        <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">

          <h2 id="document-workflows-heading" className="mt-0.5 font-semibold text-slate-950">
            Choose a task
          </h2>
        </div>

        <div className="grid lg:grid-cols-2">
          {WORKFLOWS.map((workflow, index) => {
            const Icon = workflow.icon;
            return (
              <article
                key={workflow.href}
                className={index === 0 ? "border-b border-slate-200 p-5 sm:p-6 lg:border-b-0 lg:border-r" : "p-5 sm:p-6"}
              >
                <div className="flex items-start gap-4">
                  <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${workflow.iconTone}`}>
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="mt-1 text-lg font-semibold text-slate-950">{workflow.title}</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{workflow.description}</p>
                  </div>
                </div>

                <ol className="mt-5 grid gap-2" aria-label={`${workflow.title} stages`}>
                  {workflow.steps.map((step, stepIndex) => (
                    <li
                      key={step}
                      className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm font-medium ${workflow.accent}`}
                    >
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/80 text-xs font-bold">
                        {stepIndex + 1}
                      </span>
                      {step}
                    </li>
                  ))}
                </ol>

                <IntentPrefetchLink
                  href={workflow.href}
                  className="mt-5 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
                >
                  {workflow.action}
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </IntentPrefetchLink>
              </article>
            );
          })}
        </div>
      </section>

      <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3 text-sm text-slate-600">
        <UsersRound className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
        <p>
          Renaming does not assign files to passengers. Use Document Distribution to match files to a group and send them.
        </p>
      </div>
    </div>
  );
}
