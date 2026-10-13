import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CompanyOriginalRecord } from "./company-original-record";

it("shows historical fields with their source and revision without treating them as editable current passport data", () => {
  render(<CompanyOriginalRecord record={{ source_id: "source/one", group_id: "group", status: "client_submitted", source_revision: 3, created_at: "2026-10-14T00:00:00Z", fields: { passport_number: "X1234567", place_of_birth: "Mumbai", issuing_country: "IND" } }} />);
  expect(screen.getByRole("region", { name: "Original trip record" })).toHaveTextContent("Historical details. Add a reviewed document");
  expect(screen.getByText(/client submitted · Revision 3/)).toBeInTheDocument();
  expect(screen.getByText("X1234567")).toBeInTheDocument();
  expect(screen.getByText("Mumbai")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View original record" })).toHaveAttribute("href", "/passports/source%2Fone");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
