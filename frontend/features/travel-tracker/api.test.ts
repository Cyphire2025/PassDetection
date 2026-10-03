import { beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import { travelTrackerApi } from "./api";
import { pastedNamesFile } from "./model";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock("@/lib/api/streamed-download", () => ({ downloadStreamedResponse: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ data: { total: 0, passengers: [] } });
  vi.mocked(apiClient.patch).mockResolvedValue({ data: { updated_count: 1 } });
  vi.mocked(apiClient.post).mockResolvedValue({ data: { matched_count: 1 } });
});

it("queries canonical groups and bounded server pages with abort propagation", async () => {
  const signal = new AbortController().signal;
  await travelTrackerApi.groups(" Japan ", 2, signal);
  expect(apiClient.get).toHaveBeenCalledWith("/api/v1/travel-tracker/groups", { params: { search: "Japan", page: 2, page_size: 24 }, signal });
  await travelTrackerApi.roster("group/id", { track: "flight", status: "pending", search: " Asha ", page: 3, page_size: 50 }, signal);
  expect(apiClient.get).toHaveBeenLastCalledWith("/api/v1/travel-tracker/groups/group%2Fid", { params: { track: "flight", status: "pending", search: "Asha", page: 3, page_size: 50 }, signal });
});

it("sends exact reviewed matches or a checked filtered selection without truncating IDs", async () => {
  const request = { track: "visa" as const, marked: true, passenger_ids: Array.from({ length: 1000 }, (_, index) => `passenger-${index}`) };
  await travelTrackerApi.mark("group-1", request);
  expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/travel-tracker/groups/group-1/marks", request);
  const filtered = { track: "flight" as const, marked: false, selection: { status: "marked" as const, search: "Mehta" }, expected_count: 137 };
  await travelTrackerApi.mark("group-1", filtered);
  expect(apiClient.patch).toHaveBeenLastCalledWith("/api/v1/travel-tracker/groups/group-1/marks", filtered);
});

it("uploads a multipart file for preview before any status mutation", async () => {
  const file = new File(["spreadsheet"], "visa.xlsx");
  await travelTrackerApi.preview("group-1", file, "visa", true);
  const [url, body, config] = vi.mocked(apiClient.post).mock.calls[0];
  expect(url).toBe("/api/v1/travel-tracker/groups/group-1/import/preview");
  expect(body).toBeInstanceOf(FormData);
  expect((body as FormData).get("file")).toBe(file);
  expect((body as FormData).get("track")).toBe("visa");
  expect((body as FormData).get("marked")).toBe("true");
  expect(config).toMatchObject({ headers: { "Content-Type": "multipart/form-data" }, timeout: 120_000 });
  expect(apiClient.patch).not.toHaveBeenCalled();
});

it("streams all details for marked and pending passengers using whole group export scopes", async () => {
  await travelTrackerApi.export("group/id", "Japan Tour", "visa", "marked");
  expect(downloadStreamedResponse).toHaveBeenCalledWith({ url: "/api/v1/travel-tracker/groups/group%2Fid/export", params: { track: "visa", status: "marked" }, suggestedFilename: "Japan_Tour_visa_marked.xlsx" });
  await travelTrackerApi.export("group/id", "Japan Tour", "flight", "pending");
  expect(downloadStreamedResponse).toHaveBeenLastCalledWith({ url: "/api/v1/travel-tracker/groups/group%2Fid/export", params: { track: "flight", status: "pending" }, suggestedFilename: "Japan_Tour_flight_pending.xlsx" });
});

it("preserves comma and quote characters in pasted names and discards blank lines", async () => {
  const file = pastedNamesFile(' Asha, Mehta \r\n\n Ravi "Raj" Shah \n');
  const content = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(file);
  });
  expect(file.name).toBe("pasted-passengers.csv");
  expect(content).toBe('Name\r\n"Asha, Mehta"\r\n"Ravi ""Raj"" Shah"');
  expect(() => pastedNamesFile(" \n\r\n")).toThrow("Paste at least one passenger name");
  expect(() => pastedNamesFile(Array.from({ length: 1001 }, (_, index) => `Name ${index}`).join("\n"))).toThrow("Paste up to 1,000 passenger names");
});
