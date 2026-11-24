import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Input } from "./input";

describe("input accessible descriptions", () => {
  it("retains an external description when reporting a validation error", () => {
    render(<><p id="context">Account email address</p><Input label="Email" aria-describedby="context" error="Enter a valid email" hint="For your account" /></>);
    expect(screen.getByRole("textbox", { name: "Email" })).toHaveAccessibleDescription("Account email address Enter a valid email");
    const descriptionIds = screen.getByRole("textbox").getAttribute("aria-describedby")!.split(" ");
    expect(descriptionIds.every((id) => document.getElementById(id))).toBe(true);
  });

  it("restores the hint association after an error is cleared", () => {
    const { rerender } = render(<Input label="Email" hint="For your account" error="Enter a valid email" />);
    expect(screen.getByRole("textbox")).toHaveAccessibleDescription("Enter a valid email");
    rerender(<Input label="Email" hint="For your account" />);
    expect(screen.getByRole("textbox")).toHaveAccessibleDescription("For your account");
  });
});
