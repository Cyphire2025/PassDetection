import { redirect } from "next/navigation";
import { ROUTES } from "@/constants/routes";

interface FlightTicketGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function FlightTicketGroupPage({
  params,
}: FlightTicketGroupPageProps) {
  const { groupId } = await params;
  redirect(
    ROUTES.dashboard.documentDistributionFlightLane(
      groupId,
      "international",
      "onward",
    ) as never,
  );
}
