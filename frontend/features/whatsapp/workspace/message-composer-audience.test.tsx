import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ComposerAudience } from "./message-composer-audience";
import type { ComposerController } from "./message-composer";

afterEach(cleanup);

function model(count: number): ComposerController {
  const audience = Array.from({ length: count }, (_, index) => ({
    id: String(index), name: `Synthetic person ${index + 1}`, normalized_phone_number: `+91900000${String(index).padStart(4, "0")}`,
  }));
  return { audience, selectedIds: audience.map(person => person.id), selected: audience,
    eligible: audience, current: true, pending: false, setState: vi.fn(), state: {},
    definition: { audience: "standard", message_type: "welcome" },
  } as unknown as ComposerController;
}

it("keeps refreshed recipients visible when the last reviewed page no longer exists", () => {
  const view = render(<ComposerAudience model={model(80)} />);
  const pagination = screen.getByRole("navigation", { name: "Send recipients pagination" });
  fireEvent.click(within(pagination).getByRole("button", { name: "Next" }));
  fireEvent.click(within(pagination).getByRole("button", { name: "Next" }));
  expect(screen.getByText("Synthetic person 51")).toBeInTheDocument();
  view.rerender(<ComposerAudience model={model(20)} />);
  expect(screen.getAllByRole("checkbox")).toHaveLength(20);
  expect(screen.getByText("Synthetic person 1")).toBeInTheDocument();
  expect(within(pagination).getByText("1–20 of 20")).toBeInTheDocument();
  expect(within(pagination).getByRole("button", { name: "Previous" })).toBeDisabled();
});
