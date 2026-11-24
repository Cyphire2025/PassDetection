import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PassportDateInput } from "./passport-date-input";

afterEach(cleanup);

it.each(["disabled", "readOnly"] as const)("keeps the calendar closed and the native picker inert when %s", (mode) => {
  const change = vi.fn();
  const { container } = render(<PassportDateInput label="Passport expiry" value="2030-12-31" onValueChange={change} {...{ [mode]: true }} />);
  const picker = container.querySelector<HTMLInputElement>('input[type="date"]')!;
  const show = vi.fn();
  Object.defineProperty(picker, "showPicker", { value: show });
  const button = screen.getByRole("button", { name: "Choose date from calendar" });
  expect(button).toBeDisabled();
  expect(picker).toBeDisabled();
  fireEvent.click(button);
  expect(show).not.toHaveBeenCalled();
  fireEvent.change(picker, { target: { value: "2031-01-01" } });
  expect(change).not.toHaveBeenCalled();
});

it("keeps typed and native valid dates in the same ISO contract and rejects out-of-range picker values", () => {
  const change = vi.fn();
  const { container } = render(<PassportDateInput label="Passport expiry" value="2030-12-31" minIso="2020-01-01" maxIso="2040-12-31" onValueChange={change} />);
  const input = screen.getByRole("textbox", { name: "Passport expiry" });
  fireEvent.change(input, { target: { value: "01012031" } });
  expect(input).toHaveValue("01/01/2031");
  expect(change).toHaveBeenLastCalledWith("2031-01-01");
  const picker = container.querySelector<HTMLInputElement>('input[type="date"]')!;
  fireEvent.change(picker, { target: { value: "2019-01-01" } });
  expect(change).toHaveBeenCalledTimes(1);
  fireEvent.change(picker, { target: { value: "2032-02-29" } });
  expect(input).toHaveValue("29/02/2032");
  expect(change).toHaveBeenLastCalledWith("2032-02-29");
});

it("uses the native picker for an editable date and preserves visible invalid-date feedback", () => {
  const change = vi.fn();
  const { container } = render(<PassportDateInput label="Passport expiry" value="" onValueChange={change} />);
  const picker = container.querySelector<HTMLInputElement>('input[type="date"]')!;
  const show = vi.fn();
  Object.defineProperty(picker, "showPicker", { value: show });
  fireEvent.click(screen.getByRole("button", { name: "Choose date from calendar" }));
  expect(show).toHaveBeenCalledOnce();
  const input = screen.getByRole("textbox", { name: "Passport expiry" });
  fireEvent.change(input, { target: { value: "31022031" } });
  fireEvent.blur(input);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid date as DD/MM/YYYY.");
  expect(change).not.toHaveBeenCalledWith("2031-02-31");
});
