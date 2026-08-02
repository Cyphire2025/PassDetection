import { redirect } from "next/navigation";
import { ROUTES } from "@/constants/routes";

export default function GcAppPage() {
  redirect(ROUTES.dashboard.gcAppClientManagerAccounts);
}
