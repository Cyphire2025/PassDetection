import { CompanyDashboard } from "@/features/companies/components/company-dashboard";

export default async function CompanyPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <CompanyDashboard companyId={companyId} />;
}
