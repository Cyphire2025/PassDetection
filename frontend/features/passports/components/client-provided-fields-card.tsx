"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PassportSubmission } from "@/types/passport.types";

const ClientDetailsEditDialog = dynamic(() => import("./client-details-edit-dialog").then((module) => module.ClientDetailsEditDialog));
const EDITABLE_STATUSES = new Set(["client_submitted", "confirmed", "submitted", "ai_approved", "needs_review", "staff_approved"]);

export function ClientProvidedFieldsCard({ passport, canEdit = false }: { passport: PassportSubmission; canEdit?: boolean }) {
  const [editing, setEditing] = useState(false);
  const editable = canEdit && EDITABLE_STATUSES.has(passport.status);
  const text = (key: string) => {
    for (const fields of [passport.confirmed_fields, passport.extracted_fields, passport.staff_metadata]) {
      if (fields && Object.prototype.hasOwnProperty.call(fields, key)) {
        const value = fields[key];
        return typeof value === "string" || typeof value === "number" ? String(value) : "";
      }
    }
    return "";
  };
  const agentType = text("agent_employee_type").toLowerCase();
  const agentCode = text("agent_employee_code");
  const staffCode = text("staff_code").trim();
  const values = [
    { key: "email", label: "Email entered by client", value: passport.client_email },
    { key: "phone", label: "Phone entered by client", value: passport.client_phone },
    { key: "agency", label: passport.staff_metadata?.agency_dealership_name_label || "Agency/Dealership Name", value: text("agency_dealership_name") },
    { key: "international", label: "Nearest International Airport", value: passport.departure_city },
    { key: "domestic", label: "Nearest Domestic Airport", value: passport.nearest_domestic_airport },
    { key: "base", label: "Base City", value: text("base_city") },
    { key: "staff", label: "Staff Code", value: staffCode ? `STF_${staffCode.replace(/^STF[_\-\s]+/i, "")}` : "" },
    { key: "agent", label: passport.staff_metadata?.agent_employee_code_label || "Agent/Employee Code", value: agentCode ? `${agentType === "agent" ? "AGT_" : agentType === "employee" ? "EMP_" : ""}${agentCode}` : "" },
    { key: "designation", label: "Designation", value: text("designation") },
    { key: "meal", label: "Meal Preference", value: text("meal_preference") },
    ...(passport.custom_answers ?? []).map((answer) => ({ key: `question:${answer.question_id}`, label: answer.label, value: answer.value })),
    ...(passport.custom_detail_answers ?? []).map((answer) => ({ key: `detail:${answer.detail_id}`, label: answer.label, value: answer.value })),
  ].filter((item) => Boolean(item.value));
  if (!values.length && !editable) return null;
  return (
    <Card className="rounded-3xl">
      <CardContent className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-900">Client-provided group details</h3>
          {editable && <Button type="button" variant="outline" onClick={() => setEditing(true)} aria-label="Edit client-provided group details"><Pencil className="h-4 w-4" />Edit details</Button>}
        </div>
        {values.length ? <dl className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2">
          {values.map(({ key, label, value }) => <div key={key} className="min-w-0"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words font-medium text-slate-900">{value}</dd></div>)}
        </dl> : <p className="mt-3 text-sm text-slate-500">No client-provided group details have been saved yet.</p>}
        {editing && editable && <ClientDetailsEditDialog id={passport.id} groupId={passport.group_id} onClose={() => setEditing(false)} />}
      </CardContent>
    </Card>
  );
}
