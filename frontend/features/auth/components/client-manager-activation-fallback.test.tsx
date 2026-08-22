import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ClientManagerActivationFallback } from "./client-manager-activation-fallback";

const originalPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;

afterEach(() => {
  window.history.replaceState(null, "", originalPath);
});

describe("ClientManagerActivationFallback", () => {
  it("retains a valid credential only in memory and immediately scrubs the address bar", async () => {
    const token = "A".repeat(43);
    window.history.replaceState(null, "", `/gc/activate?token=${token}`);

    render(<ClientManagerActivationFallback />);

    expect(await screen.findByRole("button", { name: "Open the mobile app" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/gc/activate");
    expect(window.location.search).toBe("");
    expect(document.body).not.toHaveTextContent(token);
  });

  it("rejects duplicate parameters, fragments, and malformed credentials", async () => {
    window.history.replaceState(null, "", "/gc/activate?token=short&token=another#fragment");

    render(<ClientManagerActivationFallback />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/incomplete or malformed/i);
    });
    expect(screen.queryByRole("button", { name: "Open the mobile app" })).not.toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
  });
});
