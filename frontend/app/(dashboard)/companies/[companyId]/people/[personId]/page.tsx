import { Suspense } from "react";
import { CompanyPersonPage } from "@/features/companies/components/company-person-page";
import { CompanyLoading } from "@/features/companies/components/company-feedback";

export default async function PersonPage({ params }: { params: Promise<{ companyId: string; personId: string }> }) {
  const { companyId, personId } = await params;
  return <Suspense fallback={<CompanyLoading />}><CompanyPersonPage companyId={companyId} personId={personId} /></Suspense>;
}
