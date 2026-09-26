import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "./error-boundary";

const { report } = vi.hoisted(() => ({ report: vi.fn(async () => "56dce0c7-74c7-4c93-adab-f1bd8298a15a") }));
vi.mock("@/lib/observability/render-errors", () => ({ reportRenderError: report }));
afterEach(() => vi.restoreAllMocks());

describe("render error fallback", () => {
  it("hides sensitive exception text, reports a support reference and retries the children", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    let broken = true;
    function Broken() { if (broken) throw new Error("secret passenger passport number"); return <p>Recovered workspace</p>; }
    render(<ErrorBoundary><Broken /></ErrorBoundary>);
    expect(screen.queryByText(/secret passenger/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Support reference:/)).toHaveTextContent("56dce0c7"));
    expect(report).toHaveBeenCalledWith(expect.any(Error), "shared");
    broken = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Recovered workspace")).toBeInTheDocument();
  });
});
