"use client";

import { FileSpreadsheet, Images } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCompanyDataExports } from "../hooks/use-company-data-exports";
import { CompanyError, companyErrorMessage } from "./company-feedback";
import { CompanyExportJobs } from "./data-exports/jobs";

export function CompanyDataExports({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const controller = useCompanyDataExports(agencyId, companyId);
  const { ready, open, setOpen, create, start } = controller;
  return <section aria-label="Company exports" className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="secondary" className="min-h-11" disabled={!ready || create.isPending}
        onClick={() => void start("excel")}>
        <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />Export Excel
      </Button>
      <Button type="button" variant="secondary" className="min-h-11" disabled={!ready || create.isPending}
        onClick={() => void start("images")}>
        <Images className="h-4 w-4" aria-hidden="true" />Export all images
      </Button>
      <Button type="button" variant="ghost" className="min-h-11" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide exports" : "Recent exports"}
      </Button>
    </div>
    {create.isError && <CompanyError message={companyErrorMessage(create.error, "The export could not be started. Try again.")} />}
    {open && <CompanyExportJobs agencyId={agencyId} companyId={companyId} controller={controller} />}
  </section>;
}
