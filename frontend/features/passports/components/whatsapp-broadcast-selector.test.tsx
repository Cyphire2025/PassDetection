import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { LinkedWhatsAppBroadcast } from "../api/upload-links.api";
import { WhatsAppBroadcastSelector } from "./whatsapp-broadcast-selector";
import type { WhatsAppMatchingFieldsByBroadcast } from "./whatsapp-match-field-selector";

const mocks = vi.hoisted(() => ({
  broadcasts: [] as LinkedWhatsAppBroadcast[],
}));

vi.mock("../hooks/use-upload-links", () => ({
  useWhatsAppBroadcastOptions: () => ({
    data: mocks.broadcasts,
    isLoading: false,
    error: null,
  }),
}));

const fields = [
  { key: "name", label: "Name" },
  { key: "mobile_number", label: "Mobile Number" },
  { key: "dob", label: "Date of Birth" },
  { key: "producer_code", label: "Producer Code" },
  { key: "location", label: "Location" },
];

function SelectorHarness({
  initialIds = [],
  initialMatchingFields = {},
}: {
  initialIds?: string[];
  initialMatchingFields?: WhatsAppMatchingFieldsByBroadcast;
}) {
  const [selectedIds, setSelectedIds] = useState(initialIds);
  const [matchingFields, setMatchingFields] = useState(initialMatchingFields);

  return (
    <>
      <WhatsAppBroadcastSelector
        selectedIds={selectedIds}
        onChange={setSelectedIds}
        selectedMatchingFields={matchingFields}
        onMatchingFieldsChange={setMatchingFields}
      />
      <output data-testid="selected-broadcasts">{JSON.stringify(selectedIds)}</output>
      <output data-testid="selected-fields">{JSON.stringify(matchingFields)}</output>
    </>
  );
}

beforeEach(() => {
  mocks.broadcasts = [{
    id: "broadcast-tour",
    name: "September Tour",
    recipient_count: 42,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-09T08:00:00Z",
    available_matching_fields: fields,
    matching_field_keys: null,
  }];
});

it("defaults a newly linked broadcast to safe familiar fields and persists additional OR fields", async () => {
  const user = userEvent.setup();
  render(<SelectorHarness />);

  await user.click(screen.getByRole("checkbox", { name: /September Tour/ }));
  const fieldSelector = screen.getByRole("heading", {
    name: "Choose identification fields",
  }).closest("section");
  expect(fieldSelector).not.toBeNull();
  const selector = within(fieldSelector!);

  expect(selector.getByRole("checkbox", { name: "Name" })).toBeChecked();
  expect(selector.getByRole("checkbox", { name: "Mobile Number" })).toBeChecked();
  expect(selector.getByRole("checkbox", { name: "Producer Code" })).not.toBeChecked();
  expect(selector.getByText(/Every imported Excel heading is available/i))
    .toHaveTextContent(/any one selected value matches/i);
  expect(selector.getByText(/Needs review instead of being assigned automatically/i)).toBeInTheDocument();

  await user.click(selector.getByRole("checkbox", { name: "Producer Code" }));
  expect(screen.getByTestId("selected-fields")).toHaveTextContent(
    JSON.stringify({
      "broadcast-tour": ["name", "mobile_number", "producer_code"],
    }),
  );
  expect(selector.getByText("Match by Name or Mobile Number or Producer Code. At least one field must stay selected."))
    .toBeInTheDocument();

  await user.type(selector.getByLabelText("Search spreadsheet headings"), "producer");
  expect(selector.getByRole("checkbox", { name: "Producer Code" })).toBeInTheDocument();
  expect(selector.queryByRole("checkbox", { name: "Location" })).not.toBeInTheDocument();
});

it("preserves a legacy null configuration until a heading is explicitly chosen", async () => {
  const user = userEvent.setup();
  render(<SelectorHarness initialIds={["broadcast-tour"]} />);

  expect(screen.getByText("Legacy matching")).toBeInTheDocument();
  expect(screen.getByText(/Existing smart matching remains active/)).toBeInTheDocument();
  expect(screen.getByTestId("selected-fields")).toHaveTextContent("{}");

  await user.click(screen.getByRole("checkbox", { name: "Producer Code" }));
  expect(screen.queryByText(/Existing smart matching remains active/)).not.toBeInTheDocument();
  expect(screen.getByTestId("selected-fields")).toHaveTextContent(
    JSON.stringify({ "broadcast-tour": ["producer_code"] }),
  );
  expect(screen.getByRole("checkbox", { name: "Producer Code" })).toBeDisabled();
});

it("allows a broadcast with no stored headings to stay on the compatible matcher", async () => {
  mocks.broadcasts = [{
    ...mocks.broadcasts[0],
    id: "broadcast-old",
    name: "Older Import",
    available_matching_fields: [],
  }];
  const user = userEvent.setup();
  render(<SelectorHarness />);

  await user.click(screen.getByRole("checkbox", { name: /Older Import/ }));
  expect(screen.getByText(/No matchable spreadsheet headings are stored/)).toBeInTheDocument();
  expect(screen.getByTestId("selected-fields")).toHaveTextContent("{}");
});

it("does not silently replace legacy matching with an arbitrary or emergency field", async () => {
  mocks.broadcasts = [{
    ...mocks.broadcasts[0],
    available_matching_fields: [
      { key: "location", label: "Location" },
      { key: "emergency_phone", label: "Emergency Phone" },
    ],
  }];
  const user = userEvent.setup();
  render(<SelectorHarness />);

  await user.click(screen.getByRole("checkbox", { name: /September Tour/ }));

  expect(screen.getByTestId("selected-fields")).toHaveTextContent("{}");
  expect(screen.getByText("Legacy matching")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Location" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Emergency Phone" })).not.toBeChecked();
});

it("enforces the backend limit while keeping selected fields removable", async () => {
  const manyFields = Array.from({ length: 33 }, (_, index) => ({
    key: `field_${index + 1}`,
    label: `Field ${index + 1}`,
  }));
  mocks.broadcasts = [{
    ...mocks.broadcasts[0],
    available_matching_fields: manyFields,
    matching_field_keys: manyFields.slice(0, 32).map((field) => field.key),
  }];
  const user = userEvent.setup();
  render(
    <SelectorHarness
      initialIds={["broadcast-tour"]}
      initialMatchingFields={{
        "broadcast-tour": manyFields.slice(0, 32).map((field) => field.key),
      }}
    />,
  );

  const extraField = screen.getByRole("checkbox", { name: "Field 33" });
  expect(extraField).toBeDisabled();
  expect(screen.getByText(/Maximum 32 fields selected/)).toBeInTheDocument();

  await user.click(screen.getByRole("checkbox", { name: "Field 1" }));
  expect(extraField).toBeEnabled();
  expect(screen.queryByText(/Maximum 32 fields selected/)).not.toBeInTheDocument();

  await user.click(extraField);
  expect(extraField).toBeChecked();
  expect(screen.getByTestId("selected-fields")).toHaveTextContent("field_33");
  expect(screen.getByText(/Maximum 32 fields selected/)).toBeInTheDocument();
});
