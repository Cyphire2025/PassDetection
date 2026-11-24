"""Literal imported-handler registrations remain visible to the review gate."""

import tempfile
import unittest
from pathlib import Path

from mcp_inventory import discover_source_routes, validate


class LiteralRouteRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write(
            "handlers.py", "async def items(body: str, user=Depends(authorize)):\n    return body\n"
        )
        self.write(
            "routes.py",
            """
from fastapi import APIRouter
from .handlers import items as items
router = APIRouter()
items = router.post("/items", include_in_schema=False)(items)
""",
        )

    def write(self, name, source):
        path = self.root / "backend/app" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def rows(self):
        return discover_source_routes(self.root)

    def reviewed(self):
        return {
            "schema_version": 1,
            "surfaces": [
                {
                    "surface": row,
                    "workflow": "synthetic.items",
                    "disposition": "internal_dependency",
                    "rationale": "Explicit test workflow classification, no automatic admission.",
                    "implementation": {"status": "planned", "adapter": None, "evidence": []},
                }
                for row in self.rows()
            ],
        }

    def test_hidden_imported_handler_and_actual_owner_are_discovered_without_importing(self):
        route = next(row for row in self.rows() if row["kind"] == "source_route")
        self.assertEqual(route["id"], "route:backend/app/routes.py:items:POST:/items")
        self.assertFalse(route["schema_visible"])
        self.assertEqual(route["implementation_source"], "backend/app/handlers.py")
        self.assertEqual(validate(self.reviewed(), self.rows(), self.root), [])

    def test_signature_and_default_authorization_changes_require_review(self):
        for source in [
            "async def items(body: bytes, user=Depends(authorize)): pass",
            "async def items(body: str, user=Depends(other_authorize)): pass",
        ]:
            with self.subTest(source=source):
                self.write(
                    "handlers.py", "async def items(body: str, user=Depends(authorize)): pass"
                )
                reviewed = self.reviewed()
                self.write("handlers.py", source)
                self.assertTrue(
                    any(
                        "contract changed" in error
                        for error in validate(reviewed, self.rows(), self.root)
                    )
                )

    def test_added_registration_and_changed_owner_with_identical_signature_require_review(self):
        reviewed = self.reviewed()
        self.write(
            "routes.py",
            (self.root / "backend/app/routes.py").read_text()
            + '\nitems = router.get("/extra")(items)\n',
        )
        self.assertTrue(
            any(
                "Unclassified workflow" in error
                for error in validate(reviewed, self.rows(), self.root)
            )
        )
        self.write("other.py", "async def items(body: str, user=Depends(authorize)): pass")
        self.write(
            "routes.py",
            'from .other import items\nitems = router.post("/items", include_in_schema=False)(items)',
        )
        self.assertTrue(
            any("contract changed" in error for error in validate(reviewed, self.rows(), self.root))
        )

    def test_actual_binding_at_registration_precedes_later_rebinding(self):
        self.write(
            "routes.py",
            """
from .handlers import items
items = router.post("/items")(items)
items = unresolved_later_value
""",
        )
        route = next(row for row in self.rows() if row["kind"] == "source_route")
        self.assertEqual(route["implementation_source"], "backend/app/handlers.py")

    def test_local_handler_and_semicolon_statement_order_are_resolved(self):
        self.write(
            "routes.py",
            'def items(body: str): return body\nitems = router.get("/local")(items); items = unknown\n',
        )
        route = next(row for row in self.rows() if row["kind"] == "source_route")
        self.assertEqual(route["implementation_source"], "backend/app/routes.py")

    def test_unresolved_cyclic_ambiguous_and_wildcard_bindings_fail_closed(self):
        cases = [
            'items = router.get("/items")(items)',
            'items = router.get("/items")(missing)',
            'items = unknown\nitems = router.get("/items")(items)',
            'if ambiguous:\n    from .handlers import items\nitems = router.get("/items")(items)',
            'from .handlers import items\nfrom .unknown import *\nitems = router.get("/items")(items)',
            'from .cycle import items\nitems = router.get("/items")(items)',
            'from .handlers import items\nif ambiguous:\n    from .unknown import *\nitems = router.get("/items")(items)',
            'from .handlers import items\nitems = other = router.get("/items")(items)',
            'from .handlers import items\nitems: Callable = router.get("/items")(items)',
            'from .handlers import items\nrouter.get("/items")(items)',
        ]
        self.write("cycle.py", "from .routes import items")
        for source in cases:
            with self.subTest(source=source):
                self.write("routes.py", source)
                with self.assertRaises(TypeError):
                    self.rows()


if __name__ == "__main__":
    unittest.main()
