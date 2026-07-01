import { PassportDetail } from "@/features/passports/components/passport-detail";

interface PassportDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function PassportDetailPage({ params }: PassportDetailPageProps) {
  const { id } = await params;
  return <PassportDetail id={id} />;
}
