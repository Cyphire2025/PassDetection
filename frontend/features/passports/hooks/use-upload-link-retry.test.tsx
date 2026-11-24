import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useUploadLinkByToken } from "./use-upload-links";

const api = vi.hoisted(() => ({ lookup: vi.fn() }));
vi.mock("../api/upload-links.api", () => ({ uploadLinksApi: { getByToken: api.lookup } }));

function PrimaryLink() {
  const link = useUploadLinkByToken("public-link");
  return <p>{link.isLoading ? "Loading link" : link.error ? "Link unavailable" : link.data?.name}</p>;
}

describe("primary upload link observer recovery", () => {
  it("retries a cached failed lookup when the primary portal remounts", async () => {
    const client = new QueryClient();
    api.lookup.mockRejectedValueOnce({ status: 404 });
    api.lookup.mockResolvedValueOnce({ id: "reopened", name: "Reopened trip" });
    const { rerender, unmount } = render(
      <QueryClientProvider client={client}><PrimaryLink key="first-visit" /></QueryClientProvider>,
    );
    try {
      await screen.findByText("Link unavailable");
      expect(api.lookup).toHaveBeenCalledTimes(1);
      rerender(<QueryClientProvider client={client}><PrimaryLink key="return-visit" /></QueryClientProvider>);
      expect(await screen.findByText("Reopened trip")).toBeInTheDocument();
      expect(api.lookup).toHaveBeenCalledTimes(2);
    } finally {
      unmount();
      client.clear();
    }
  });
});
