import { GlobalSearch } from "@/features/search/components/global-search";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

    const input = screen.getByRole("combobox", {
      name: "Search passports and groups",
    });
    expect(input).toHaveAttribute("aria-expanded", "false");
    await user.type(input, "singapore");

    await waitFor(() =>
      expect(
        screen.getByRole("listbox", { name: "Search results" }),
      ).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    expect(input).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}{Enter}");
    expect(mocks.push).toHaveBeenCalledWith("/passports/groups/group-2");
  });

  it("announces empty results and closes with Escape", async () => {
    mocks.global.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<GlobalSearch />);

    const input = screen.getByRole("combobox", {
      name: "Search passports and groups",
    });
    await user.type(input, "missing");
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "No matching passports or groups found",
      );
    });
    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("clears an active query without navigating", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    const input = screen.getByRole("combobox", {
      name: "Search passports and groups",
    });
    await user.type(input, "aarav");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("distinguishes a failed search from empty success and retries", async () => {
    mocks.global.mockRejectedValueOnce(new Error("temporarily unavailable"));
    const user = userEvent.setup();
    render(<GlobalSearch />);
    await user.type(screen.getByRole("combobox"), "aarav");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "temporarily unavailable",
    );
    expect(
      screen.queryByText("No matching passports or groups found."),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry search" }));
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
  });

  it("cancels superseded requests and exposes the search shortcut", async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    const input = screen.getByRole("combobox");
    await user.keyboard("{Control>}k{/Control}");
    expect(input).toHaveFocus();
    await user.type(input, "first");
    await waitFor(() => expect(mocks.global).toHaveBeenCalled());
    const signal = mocks.global.mock.calls.at(-1)?.[1] as AbortSignal;
    await user.type(input, " next");
    expect(signal.aborted).toBe(true);
  });
});
