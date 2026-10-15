import { CompanyAgencyScope } from "@/features/companies/components/company-agency-scope";

export default function CompaniesLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-w-0 space-y-5"><CompanyAgencyScope>{children}</CompanyAgencyScope></div>;
}
