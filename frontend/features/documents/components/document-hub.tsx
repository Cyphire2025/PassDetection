"use client";

import Link from "next/link";
import { FilePenLine, SendToBack } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";

const OPTIONS = [
  {
    title: "Rename Documents",
    description: "Upload raw visa and ticket PDFs, extract names, detect document type, and download renamed files.",
    href: ROUTES.dashboard.documentRename,
    icon: FilePenLine,
    action: "Open Rename Tool",
  },
  {
    title: "Document Distribution",
    description: "Upload reviewed visas and tickets into a group, match them to passengers, and save the distribution list.",
    href: ROUTES.dashboard.documentDistribution,
    icon: SendToBack,
    action: "Open Distribution",
  },
];

export function DocumentHub() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Documents"
        description="Prepare travel PDFs before sending them to passengers."
      />

      <div className="grid gap-4 md:grid-cols-2">
        {OPTIONS.map((option) => {
          const Icon = option.icon;
          return (
            <Card key={option.href} className="transition hover:border-blue-200 hover:shadow-md">
              <CardContent className="flex h-full flex-col gap-5 p-6">
                <div className="flex items-start gap-4">
                  <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                    <Icon className="h-6 w-6" />
                  </span>
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">{option.title}</h2>
                    <p className="mt-2 text-sm leading-6 text-slate-500">{option.description}</p>
                  </div>
                </div>
                <Link href={option.href as never} className="mt-auto block">
                  <Button className="w-full" variant="outline">
                    {option.action}
                  </Button>
                </Link>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
