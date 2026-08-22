import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivationForm } from "./activation-form";

const api = vi.hoisted(() => ({
  activate: vi.fn(),
  verifyMfa: vi.fn(),
}));

vi.mock("../api/auth.api", () => ({ authApi: api }));

const originalPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;

afterEach(() => {
  api.activate.mockReset();
  api.verifyMfa.mockReset();
  window.history.replaceState(null, "", originalPath);
});

function renderForm() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ActivationForm />
    </QueryClientProvider>,
  );
}

describe("ActivationForm credential handling", () => {
  it("scrubs the URL while retaining the token only for the activation request", async () => {
    const token = "A".repeat(43);
    window.history.replaceState(null, "", `/activate?token=${token}`);
    api.activate.mockResolvedValue({
      status: "mfa_required",
      challenge_token: "C".repeat(43),
      expires_at: "2099-08-22T13:00:00Z",
      setup_secret: null,
      otpauth_uri: null,
    });
    const user = userEvent.setup();

    renderForm();

    await screen.findByRole("heading", { name: "Activate your account" });
    expect(window.location.pathname).toBe("/activate");
    expect(window.location.search).toBe("");
    expect(document.body).not.toHaveTextContent(token);
    await user.type(screen.getByLabelText(/^New password/), "ReplacementPass2");
    await user.type(screen.getByLabelText(/^Confirm password/), "ReplacementPass2");
    await user.click(screen.getByRole("button", { name: "Set password and continue" }));

    await waitFor(() => {
      expect(api.activate).toHaveBeenCalledWith(token, "ReplacementPass2");
    });
  });

  it("rejects duplicate or malformed token parameters before any API request", async () => {
    window.history.replaceState(null, "", "/activate?token=short&token=duplicate");

    renderForm();

    expect(await screen.findByRole("heading", { name: "Activation link unavailable" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(api.activate).not.toHaveBeenCalled();
  });
});
