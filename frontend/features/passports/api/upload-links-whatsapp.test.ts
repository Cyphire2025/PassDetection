import { beforeEach, describe, expect, it, vi } from "vitest";

const { put } = vi.hoisted(() => ({ put: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { put } }));
import { uploadLinksApi } from "./upload-links.api";

describe("upload-group WhatsApp matching configuration", () => {
  beforeEach(() => put.mockReset());

  it("saves selected spreadsheet headings per linked broadcast", async () => {
    put.mockResolvedValue({ data: { broadcasts: [] } });
    const selectedFields = {
      "broadcast-a": ["name", "mobile_number", "producer_code"],
      "broadcast-b": ["location"],
    };

    await uploadLinksApi.updateWhatsAppLinks(
      "client-group-a",
      ["broadcast-a", "broadcast-b"],
      selectedFields,
    );

    expect(put).toHaveBeenCalledWith(
      "/api/v1/upload-links/client-group-a/whatsapp-links",
      {
        whatsapp_broadcast_group_ids: ["broadcast-a", "broadcast-b"],
        matching_fields_by_broadcast: selectedFields,
      },
    );
  });

  it("omits the additive field map when an older caller does not provide it", async () => {
    put.mockResolvedValue({ data: { broadcasts: [] } });
    await uploadLinksApi.updateWhatsAppLinks("client-group-a", ["broadcast-a"]);

    expect(put).toHaveBeenCalledWith(
      "/api/v1/upload-links/client-group-a/whatsapp-links",
      { whatsapp_broadcast_group_ids: ["broadcast-a"] },
    );
  });
});
