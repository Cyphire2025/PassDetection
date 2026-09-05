// @vitest-environment jsdom
import { StrictMode, type PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useIdentityActionToken } from "./use-identity-action-token";

const token = "single-use-activation-token-0123456789abcdef0123456789";
const strictWrapper = ({ children }: PropsWithChildren) => (
  <StrictMode>{children}</StrictMode>
);

afterEach(() => window.history.replaceState(null, "", "/"));

describe("identity action credentials", () => {
  it("survives effect replay after scrubbing the URL, then clears on unmount", async () => {
    window.history.replaceState(
      { preserved: true },
      "",
      `/activate?token=${token}`,
    );
    const { result, unmount } = renderHook(useIdentityActionToken, {
      wrapper: strictWrapper,
    });
    await waitFor(() => expect(result.current.tokenState).toBe("ready"));
    expect(result.current.readToken()).toBe(token);
    expect(window.location.pathname).toBe("/activate");
    expect(window.location.search).toBe("");
    expect(window.history.state).toEqual({ preserved: true });
    const read = result.current.readToken;
    unmount();
    expect(read()).toBeNull();
    await act(async () => Promise.resolve());
    expect(read()).toBeNull();
  });

  it.each([
    "/activate",
    "/activate?token=short",
    `/activate?token=${token}&token=${token}`,
    `/recover?token=${token}&next=/dashboard`,
    `/recover?token=${token}#untrusted`,
  ])("rejects malformed or ambiguous URLs: %s", async (url) => {
    window.history.replaceState(null, "", url);
    const { result } = renderHook(useIdentityActionToken, {
      wrapper: strictWrapper,
    });
    await waitFor(() => expect(result.current.tokenState).toBe("invalid"));
    expect(result.current.readToken()).toBeNull();
    expect(window.location.search).toBe("");
  });
});
