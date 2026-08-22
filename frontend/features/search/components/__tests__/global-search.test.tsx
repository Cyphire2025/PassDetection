import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GlobalSearch } from "@/features/search/components/global-search";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  global: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/features/search/api/search.api", () => ({
  searchApi: { global: mocks.global },
}));

const results = [
  {
    id: "passport-1",
    type: "passport" as const,
    title: "Aarav Shah",
    subtitle: "P1234567",
    group_id: "group-1",
    group_name: "Tokyo 2026",
    destination: "Tokyo",
    client_phone: null,
  },
  {
    id: "group-2",
    type: "group" as const,
    title: "Singapore 2026",
    subtitle: null,
    group_id: "group-2",
    group_name: "Singapore 2026",
    destination: "Singapore",
    client_phone: null,
  },
];

describe("GlobalSearch", () => {
  beforeEach(() => {
    mocks.push.mockReset();
    mocks.global.mockReset().mockResolvedValue(results);
  });

  it("exposes combobox semantics and supports arrow-key selection", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);

    const input = screen.getByRole("combobox", { name: "Search passports and groups" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.type(input, "singapore");

    await waitFor(() => expect(screen.getByRole("listbox", { name: "Search results" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    expect(input).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}{Enter}");
    expect(mocks.push).toHaveBeenCalledWith("/passports/groups/group-2");
  });

  it("announces empty results and closes with Escape", async () => {
    mocks.global.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<GlobalSearch />);

    const input = screen.getByRole("combobox", { name: "Search passports and groups" });
    await user.type(input, "missing");
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("No matching passports or groups found");
    });
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("clears an active query without navigating", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    const input = screen.getByRole("combobox", { name: "Search passports and groups" });
    await user.type(input, "aarav");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
