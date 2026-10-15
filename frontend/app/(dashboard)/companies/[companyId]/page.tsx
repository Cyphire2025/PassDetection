import { Suspense } from "react";
import { CompanyDashboard } from "@/features/companies/components/company-dashboard";
import { CompanyLoading } from "@/features/companies/components/company-feedback";

export default async function CompanyPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <Suspense fallback={<CompanyLoading />}><CompanyDashboard companyId={companyId} /></Suspense>;
}
