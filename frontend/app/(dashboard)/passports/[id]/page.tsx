import { PassportDetail } from "@/features/passports/components/passport-detail";

interface PassportDetailPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function PassportDetailPage({
  params,
  searchParams,
}: PassportDetailPageProps) {
  const { id } = await params;
  const query = serializeSearchParams(await searchParams);
  return <PassportDetail key={id} id={id} navigationQuery={query} />;
}

function serializeSearchParams(
  searchParams: Record<string, string | string[] | undefined>,
) {
  const query = new URLSearchParams();
  Object.entries(searchParams).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => query.append(key, item));
    } else if (value !== undefined) {
      query.set(key, value);
    }
  });
  return query.toString();
}
