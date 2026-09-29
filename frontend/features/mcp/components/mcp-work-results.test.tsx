import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mcpApi, type McpArtifact, type McpOperation } from "../api/mcp.api";
import { McpFiles, McpToolInventory, McpWorkflows } from "./mcp-work-results";

vi.mock("../api/mcp.api", async (original) => {
  const actual = await original<typeof import("../api/mcp.api")>();
  return { ...actual, mcpApi: { ...actual.mcpApi, operations: vi.fn(), artifacts: vi.fn(), inventory: vi.fn() } };
});
const clients: QueryClient[] = [];
const operation: McpOperation = { id: "operation-a", operation: "create_group", workflow_id: "workflow-a", connection_id: "connection-a", status: "running", progress: 0.4, stage: "generating", revision: 1, created_entities: [], created_at: "2026-09-29T12:00:00Z", updated_at: "2026-09-29T12:01:00Z", completed_at: null };
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mcpApi.operations).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(mcpApi.artifacts).mockResolvedValue({ items: [], next_offset: null });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("shows saved progress and uncertain outcomes without linking untrusted destinations", async () => {
  vi.mocked(mcpApi.operations).mockResolvedValue({ items: [
    { ...operation, created_entities: [{ entity_type: "client_group", entity_id: "one", path: "/passports/groups/00000000-0000-4000-8000-000000000001" }, { entity_type: "client_group", entity_id: "two", path: "https://attacker.example/" }] },
    { ...operation, id: "operation-b", status: "unknown" },
  ], next_offset: null });
  mount(<McpWorkflows />);
  expect(await screen.findByText("Outcome uncertain")).toBeVisible();
  expect(screen.getByRole("progressbar", { name: "Workflow progress" })).toHaveAttribute("value", "0.4");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByRole("link")).toHaveAttribute("href", "/passports/groups/00000000-0000-4000-8000-000000000001");
  expect(screen.getByText("operation-a")).toBeVisible();
});

it("follows the server continuation for workflow pages", async () => {
  vi.mocked(mcpApi.operations).mockResolvedValueOnce({ items: [operation], next_offset: 25 }).mockResolvedValue({ items: [], next_offset: null });
  mount(<McpWorkflows />);
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await waitFor(() => expect(mcpApi.operations).toHaveBeenCalledWith(25, expect.any(AbortSignal)));
  expect(await screen.findByText("No saved workflows on this page.")).toBeVisible();
});

it("distinguishes available files from acknowledged delivery", async () => {
  const artifact: McpArtifact = { id: "artifact-a", connection_id: "connection-a", group_id: "group-a", direction: "export", purpose: "passport_excel", filename: "Passengers.xlsx", byte_size: 1200, created_at: "2026-09-29T12:00:00Z", expires_at: "2026-09-29T13:00:00Z", status: "available", delivered_at: null };
  vi.mocked(mcpApi.artifacts).mockResolvedValue({ items: [artifact, { ...artifact, id: "artifact-b", filename: "Delivered.xlsx", status: "delivered", delivered_at: "2026-09-29T12:01:00Z" }], next_offset: null });
  mount(<McpFiles />);
  expect(await screen.findByText("Passengers.xlsx")).toBeVisible();
  expect(screen.getByText("available")).toBeVisible();
  expect(screen.getByText("delivered", { exact: true })).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("keeps header upload preparation and imported records distinct from message delivery", async () => {
  const base: McpArtifact = { id: "media-ready", connection_id: "connection-a", group_id: null, direction: "upload", kind: "whatsapp_header", purpose: "whatsapp_header", filename: "header.png", byte_size: 1200, created_at: "2026-09-29T12:00:00Z", expires_at: "2026-09-29T13:00:00Z", status: "ready", delivered_at: null };
  vi.mocked(mcpApi.artifacts).mockResolvedValue({ items: [base,
    { ...base, id: "media-unknown", filename: "uncertain.png", status: "unknown" },
    { ...base, id: "media-pending", filename: "pending.png", status: "uploading" },
    { ...base, id: "contacts", kind: "contact_workbook", filename: "contacts.xlsx", status: "imported" },
    { ...base, id: "pdf", kind: "artifact", filename: "draft.pdf", status: "ingested" },
  ], next_offset: null });
  mount(<McpFiles />);
  expect(await screen.findByText("Header image ready")).toBeVisible();
  expect(screen.getByText("Upload outcome uncertain")).toBeVisible();
  expect(screen.getByText("Upload receipt pending")).toBeVisible();
  expect(screen.getByText("Broadcast created")).toBeVisible();
  expect(screen.getByText("Document draft created")).toBeVisible();
  expect(screen.queryByText("delivered", { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("shows actual release tools and deployment capability restrictions", async () => {
  vi.mocked(mcpApi.inventory).mockResolvedValue({ tool_count: 2, environment: "qualification", revision: "rev", qualification: "in_progress", tools: [
    { name: "list_groups", description: "Find groups.\nAdditional protocol details.", capability: "mcp:read", read_only: true, deployment_available: true, qualification: "in_progress" },
    { name: "create_group", description: "Create a group.", capability: "mcp:change", read_only: false, deployment_available: false, qualification: "in_progress" },
  ], file_transports: [] });
  mount(<McpToolInventory />);
  expect(await screen.findByText("Find groups.")).toBeVisible();
  expect(screen.getByText("Disabled in deployment")).toBeVisible();
  expect(screen.getByText(/2 tools.*Qualification in progress/)).toBeVisible();
  expect(screen.queryByText("Additional protocol details.")).not.toBeInTheDocument();
});

it("keeps unavailable workflow data distinct from an empty list", async () => {
  vi.mocked(mcpApi.operations).mockRejectedValue(new Error("Workflow data unavailable"));
  mount(<McpWorkflows />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Workflow data unavailable");
  expect(screen.queryByText("No saved workflows on this page.")).not.toBeInTheDocument();
});
