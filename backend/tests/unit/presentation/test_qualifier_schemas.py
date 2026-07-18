from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.presentation.api.v1.schemas.client_group_schemas import (
    CreateClientGroupRequest,
    CreateQualifierSelectionRequest,
)


class QualifierSchemaTests(unittest.TestCase):
    def test_client_group_flag_defaults_off_for_old_clients(self) -> None:
        request = CreateClientGroupRequest(name="Legacy Link")

        self.assertFalse(request.relation_with_qualifier_enabled)

    def test_schema_requires_exactly_one_path(self) -> None:
        self.assertTrue(
            CreateQualifierSelectionRequest(
                is_self=True,
            ).is_self
        )
        relation = CreateQualifierSelectionRequest(
            is_self=False,
            relation_code="spouse",
        )
        self.assertEqual(relation.relation_code, "spouse")

        for payload in (
            {"is_self": True, "relation_code": "spouse"},
            {"is_self": False},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    CreateQualifierSelectionRequest(**payload)

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateQualifierSelectionRequest(
                is_self=True,
                unrelated_person_id="not-allowed",
            )


if __name__ == "__main__":
    unittest.main()
