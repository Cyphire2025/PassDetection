"""Behavioral contracts for discovery drift and truthful evidence classification."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from mcp_inventory import discover, validate


class WorkflowInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("backend/contracts/api.openapi.json", json.dumps({"paths": {}}))
        self.write("backend/app/routes.py", '''
from fastapi import APIRouter
router = APIRouter()
@router.post("/items", include_in_schema=False)
async def add_item(body: str):
    return body
''')
        self.write("frontend/features/items/api/items.api.ts", '''
export const itemsApi = {
  create: async (name: string) => apiClient.post("/items", {name}),
};
''')
        self.write("frontend/app/items/page.tsx", "export default function Items() { return null; }")

    def write(self, name: str, content: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def reviewed(self) -> dict:
        return {"schema_version": 1, "surfaces": [
            {"surface": row, "workflow": "items.create", "disposition": "implement",
             "phase": 5, "rationale": "Create retained items through authorized business service.",
             "implementation": {"status": "planned", "adapter": None, "evidence": []}}
            for row in discover(self.root)
        ]}

    def test_hidden_source_route_and_frontend_workflows_are_discovered_without_openapi(self) -> None:
        rows = discover(self.root)
        self.assertEqual({row["kind"] for row in rows}, {
            "source_route", "route_registration", "frontend_callable", "frontend_api_contract", "frontend_page",
        })
        self.assertFalse(next(row for row in rows if row["kind"] == "source_route")["schema_visible"])
        self.assertEqual(validate(self.reviewed(), rows, self.root), [])

    def test_new_source_route_fails_even_when_openapi_does_not_change(self) -> None:
        matrix = self.reviewed()
        path = self.root / "backend/app/routes.py"
        path.write_text(path.read_text() + '\n@router.delete("/items/{id}")\ndef remove(id: str): pass\n')
        self.assertTrue(any("Unclassified workflow" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_new_frontend_action_and_page_fail(self) -> None:
        matrix = self.reviewed()
        self.write("frontend/features/items/api/items.api.ts", "export async function exportItems() { return apiClient.get('/export'); }")
        self.write("frontend/app/reports/page.tsx", "export default function Reports() { return null; }")
        errors = validate(matrix, discover(self.root), self.root)
        self.assertTrue(any("exportItems" in error for error in errors))
        self.assertTrue(any("reports/page.tsx" in error for error in errors))

    def test_changed_auth_contract_requires_review(self) -> None:
        matrix = self.reviewed()
        path = self.root / "backend/app/routes.py"
        path.write_text(path.read_text().replace("body: str", "body: str, user = Depends(auth)"))
        self.assertTrue(any("contract changed" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_registration_changes_are_reviewed(self) -> None:
        self.write("backend/app/router.py", 'router.include_router(items, prefix="/items")')
        matrix = self.reviewed()
        self.write("backend/app/router.py", 'router.include_router(items, prefix="/public")')
        self.assertTrue(any("contract changed" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_router_constructor_prefix_changes_are_reviewed(self) -> None:
        matrix = self.reviewed()
        path = self.root / "backend/app/routes.py"
        path.write_text(path.read_text().replace("APIRouter()", 'APIRouter(prefix="/public")'))
        self.assertTrue(any("contract changed" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_new_non_async_frontend_action_changes_facade_contract(self) -> None:
        matrix = self.reviewed()
        path = self.root / "frontend/features/items/api/items.api.ts"
        path.write_text(path.read_text().replace("};", "  remove: (id) => apiClient.delete(id),\n};"))
        self.assertTrue(any("contract changed" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_classification_cannot_claim_unsupported_exclusion_or_verification(self) -> None:
        matrix = self.reviewed()
        matrix["surfaces"][0]["disposition"] = "manual_removal"
        self.assertTrue(any("agreed boundary" in error for error in validate(matrix, discover(self.root), self.root)))
        matrix = self.reviewed()
        matrix["surfaces"][0]["implementation"]["status"] = "verified"
        errors = validate(matrix, discover(self.root), self.root)
        self.assertTrue(any("retained evidence" in error for error in errors))
        self.assertTrue(any("concrete adapter" in error for error in errors))

    def test_duplicate_rows_and_removed_workflows_fail(self) -> None:
        matrix = self.reviewed()
        matrix["surfaces"].append(copy.deepcopy(matrix["surfaces"][0]))
        self.assertTrue(any("Duplicate" in error for error in validate(matrix, discover(self.root), self.root)))
        (self.root / "frontend/app/items/page.tsx").unlink()
        self.assertTrue(any("Stale workflow" in error for error in validate(self.reviewed() | {"surfaces": matrix["surfaces"]}, discover(self.root), self.root)))

    def test_allowed_workflow_cannot_be_marked_not_applicable(self) -> None:
        matrix = self.reviewed()
        matrix["surfaces"][0]["implementation"]["status"] = "not_applicable"
        self.assertTrue(any("implementation state" in error for error in validate(matrix, discover(self.root), self.root)))

    def test_new_mcp_tool_requires_review(self) -> None:
        matrix = self.reviewed()
        self.write("backend/app/mcp.py", '@server.tool()\nasync def unsafe_request(url: str): pass\n')
        errors = validate(matrix, discover(self.root), self.root)
        self.assertTrue(any("Unclassified workflow surface: mcp_tool:" in error for error in errors))

    def test_verified_evidence_cannot_escape_repository(self) -> None:
        matrix = self.reviewed()
        external = Path(self.temporary.name).parent / (Path(self.temporary.name).name + "-evidence.txt")
        external.write_text("unrelated", encoding="utf-8")
        self.addCleanup(external.unlink)
        matrix["surfaces"][0]["implementation"] = {
            "status": "verified", "adapter": "named.business.operation", "evidence": [str(external)],
        }
        self.assertTrue(any("retained evidence" in error for error in validate(matrix, discover(self.root), self.root)))


if __name__ == "__main__":
    unittest.main()
