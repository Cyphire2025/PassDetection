import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { CompanyGroup, CompanyReference } from "../types";
import { CompanyMatchResolution } from "./company-match-resolution";
import { CompanyMatchingDialog } from "./company-matching-dialog";
import { CompanyPassports } from "./company-passports";
import { CompanyReassignmentDialog } from "./company-reassignment-dialog";
import { CompanySettings } from "./company-settings";
import {
  cleanupCompanyAuthority, companyActor, companyWrites, match, queuedCompanyMutation,
  resetCompanyAuthority,
} from "../test-support/mutation-authority";

vi.mock("@/lib/api/client", () => ({ default: {
  get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
} }));
beforeEach(resetCompanyAuthority);
afterEach(cleanupCompanyAuthority);

it.each(["matching", "resolution", "passport", "reassignment", "settings"] as const)(
  "refuses a queued %s form write after the initiating actor changes",
  async (operation) => {
    const context = queuedCompanyMutation();
    const close = vi.fn();
    switch (operation) {
      case "matching":
        render(<CompanyMatchingDialog agencyId="agency" companyId="company"
          group={{ id: "group", name: "Synthetic group" } as CompanyGroup} onClose={close} />, context);
        fireEvent.click(await screen.findByRole("button", { name: "Run matching preview" }));
        break;
      case "resolution":
        render(<CompanyMatchResolution agencyId="agency" companyId="company" groupId="group"
          match={match} groupRevision={9} onPending={vi.fn()} onBack={close} onRefresh={vi.fn()} />, context);
        fireEvent.click(screen.getByRole("radio", { name: /Use the proposed traveller/ }));
        fireEvent.change(screen.getByLabelText(/Evidence and decision reason/), { target: { value: "Reviewed synthetic association evidence." } });
        fireEvent.click(screen.getByRole("checkbox"));
        fireEvent.click(screen.getByRole("button", { name: "Record roster decision" }));
        break;
      case "passport":
        render(<CompanyPassports agencyId="agency" companyId="company" travellerId="traveller" onClose={close} />, context);
        fireEvent.click(await screen.findByRole("button", { name: /Change status/ }));
        fireEvent.click(screen.getByRole("checkbox"));
        fireEvent.click(screen.getByRole("button", { name: "Confirm passport status" }));
        break;
      case "reassignment":
        render(<CompanyReassignmentDialog
          group={{ id: "group", agency_id: "agency", name: "Synthetic group" } as UploadLinkResponse}
          target={{ id: "company", name: "Synthetic company" } as CompanyReference}
          onSuccess={vi.fn(async () => undefined)} onClose={close} />, context);
        fireEvent.change(await screen.findByLabelText(/Reason for reassignment/), { target: { value: "Correct synthetic group assignment." } });
        fireEvent.click(screen.getByRole("button", { name: "Confirm reassignment" }));
        break;
      case "settings":
        render(<CompanySettings agencyId="agency" companyId="company" active />, context);
        fireEvent.click(await screen.findByRole("switch"));
        break;
    }
    await waitFor(() => expect(context.entered).toHaveBeenCalledOnce());
    act(() => useAuthStore.setState({ user: { ...companyActor, id: "replacement-owner" } }));
    // A suspended mutation can outlive the replacement account's query reload.
    if (operation === "passport") {
      await screen.findByRole("button", { name: /Change status/ });
    } else if (operation === "settings") {
      await screen.findByRole("switch");
    }
    await act(async () => { context.release(); });
    await waitFor(() => expect(context.client.getMutationCache().getAll()[0]?.state.status).not.toBe("pending"));
    for (const write of companyWrites()) expect(write).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
    expect(context.client.getMutationCache().getAll()[0]?.state.error).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  },
);
