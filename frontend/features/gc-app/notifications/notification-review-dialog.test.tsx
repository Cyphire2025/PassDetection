import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationReviewDialog } from "./notification-review-dialog";
import { draft, preview } from "./notification-test-fixtures";

afterEach(cleanup);
const props = () => ({ draft, preview: preview(), busy: false, recovering: false, resending: false, onClose: vi.fn(), onRefresh: vi.fn(), onSend: vi.fn() });

describe("Explicit phone-send review", () => {
  it("shows exact message, groups and audience counts without sending on open", async () => {
    const value = props();
    render(<NotificationReviewDialog {...value} />);
    expect(screen.getByLabelText("Phone alert preview")).toHaveTextContent(draft.title);
    expect(screen.getByText("Eligible recipients").nextSibling).toHaveTextContent("12");
    expect(screen.getByText("Recipients without an active device").nextSibling).toHaveTextContent("4");
    expect(screen.getByText(/Android only/)).toBeVisible();
    expect(value.onSend).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Send notification" }));
    expect(value.onSend).toHaveBeenCalledTimes(1);
  });

  it("blocks an expired review and a zero-person audience", () => {
    const value = props();
    const view = render(<NotificationReviewDialog {...value} preview={{ ...value.preview, expires_at: new Date(Date.now() - 10_000).toISOString() }} />);
    expect(screen.getByRole("button", { name: "Send notification" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("expired");
    view.rerender(<NotificationReviewDialog {...value} preview={{ ...value.preview, recipient_count: 0 }} />);
    expect(screen.getByRole("button", { name: "Send notification" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("No currently authorized");
  });

  it("warns about no registered devices without claiming delivery", () => {
    const value = props();
    render(<NotificationReviewDialog {...value} preview={{ ...value.preview, eligible_device_count: 0, provider_enabled: false }} />);
    expect(screen.getByText(/cannot reach a phone right now/)).toBeVisible();
    expect(screen.getByText(/Phone delivery is disabled/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Send notification" })).toBeEnabled();
  });

  it("distinguishes a deliberate resend from retrying one uncertain request", () => {
    const value = props();
    const view = render(<NotificationReviewDialog {...value} resending />);
    expect(screen.getByRole("button", { name: "Send again" })).toBeVisible();
    expect(screen.getByText(/can receive it again/)).toBeVisible();
    view.rerender(<NotificationReviewDialog {...value} recovering />);
    expect(screen.getByRole("button", { name: "Retry same send request" })).toBeVisible();
    expect(screen.getByText(/without creating a second send/)).toBeVisible();
  });

  it("names a selected trip that became unavailable and blocks a silently narrowed send", () => {
    const value = props();
    render(<NotificationReviewDialog {...value} preview={{ ...value.preview, group_ids: [], group_names: [], group_count: 0 }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Synthetic Hill Trip");
    expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
    expect(screen.getByRole("button", { name: "Send notification" })).toBeDisabled();
  });
});
