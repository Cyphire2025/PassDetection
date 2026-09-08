import { useState, type ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RelationQualifierStep } from "./relation-qualifier-step";
import { buildQualifierSelectionRequest, type QualifierPath } from "../services/relation-qualifier";

const options = [{ code: "spouse", label: "Spouse" }, { code: "sister", label: "Sister" }];
type Props = ComponentProps<typeof RelationQualifierStep>;

function Harness({ listEnabled = true, otherEnabled = false, isSaving = false, initialPath = null, initialCode = "", initialOther = "", onSave = vi.fn(), relationOptions = options }: {
  listEnabled?: boolean; otherEnabled?: boolean; isSaving?: boolean; initialPath?: QualifierPath;
  initialCode?: string; initialOther?: string; onSave?: (value: unknown) => void; relationOptions?: Props["options"];
}) {
  const [path, setPath] = useState<QualifierPath>(initialPath);
  const [code, setCode] = useState(initialCode);
  const [other, setOther] = useState(initialOther);
  return <RelationQualifierStep path={path} relationCode={code} otherRelation={other}
    listEnabled={listEnabled} otherEnabled={otherEnabled} options={relationOptions} isSaving={isSaving}
    onPathChange={setPath} onRelationChange={setCode} onOtherRelationChange={setOther}
    onContinue={() => onSave(buildQualifierSelectionRequest(path, code, relationOptions, other, { listEnabled, otherEnabled }))} />;
}

describe("passenger qualifier relationship choice", () => {
  it("keeps Self and the existing relationship list for a list-only link", async () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Passenger's relationship" }), "sister");
    expect(screen.getByRole("radio", { name: /Choose from list/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSave).toHaveBeenCalledWith({ is_self: false, relation_code: "sister" });
  });

  it("hides the standard list for an Other-only link and saves the custom relationship", async () => {
    const onSave = vi.fn();
    render(<Harness listEnabled={false} otherEnabled onSave={onSave} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Choose from list/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    await userEvent.type(screen.getByRole("textbox", { name: "Specify relationship" }), "  Cousin  ");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSave).toHaveBeenCalledWith({ is_self: false, relation_code: "other", other_relation: "Cousin" });
  });

  it("makes list, Other and Self mutually exclusive even when both fields contain values", async () => {
    const onSave = vi.fn();
    render(<Harness otherEnabled onSave={onSave} />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "spouse");
    await userEvent.type(screen.getByRole("textbox"), "Colleague");
    expect(screen.getByRole("radio", { name: /Choose from list/ })).toHaveAttribute("aria-checked", "false");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSave).toHaveBeenLastCalledWith({ is_self: false, relation_code: "other", other_relation: "Colleague" });
    await userEvent.click(screen.getByRole("radio", { name: /Self/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSave).toHaveBeenLastCalledWith({ is_self: true, relation_code: null });
    await userEvent.click(screen.getByRole("radio", { name: /Choose from list/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSave).toHaveBeenLastCalledWith({ is_self: false, relation_code: "spouse" });
  });

  it.each(["   ", "Self", "x".repeat(101), "Friend\nOther"])("blocks invalid custom text %j with an accessible explanation", (value) => {
    render(<Harness otherEnabled initialPath="other" initialOther={value} />);
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("status")).not.toBeEmptyDOMElement();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("uses arrow keys to select and focus only enabled methods", () => {
    render(<Harness otherEnabled listEnabled={false} />);
    const self = screen.getByRole("radio", { name: /Self/ });
    const other = screen.getByRole("radio", { name: /Other relationship/ });
    self.focus();
    fireEvent.keyDown(self, { key: "ArrowRight" });
    expect(other).toHaveFocus();
    expect(other).toHaveAttribute("aria-checked", "true");
    expect(self).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(other, { key: "ArrowLeft" });
    expect(self).toHaveFocus();
    expect(self).toHaveAttribute("aria-checked", "true");
  });

  it("rejects a stale selection when its method is no longer enabled", () => {
    render(<Harness listEnabled={false} otherEnabled initialPath="relation" initialCode="spouse" />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Self/ })).toHaveAttribute("tabindex", "0");
  });

  it("leaves Self usable when the provider supplies no list entries", async () => {
    render(<Harness relationOptions={[]} />);
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Self/ }));
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("locks every method and field while the selection is being saved", () => {
    render(<Harness otherEnabled isSaving initialPath="other" initialOther="Cousin" />);
    screen.getAllByRole("radio").forEach((radio) => expect(radio).toBeDisabled());
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });
});
