from __future__ import annotations

import unittest

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.qualifier_relations import (
    QualifierRelation,
    hash_qualifier_selection_token,
    normalize_qualifier_choice,
    qualifier_relation_options,
)


class QualifierRelationTests(unittest.TestCase):
    def test_every_approved_relation_has_a_stable_code_and_label(self) -> None:
        options = qualifier_relation_options()

        self.assertEqual(
            [option["code"] for option in options],
            [relation.value for relation in QualifierRelation],
        )
        self.assertTrue(all(option["label"] for option in options))
        self.assertNotIn("friend", {option["code"] for option in options})
        self.assertNotIn("colleague", {option["code"] for option in options})
        self.assertNotIn("acquaintance", {option["code"] for option in options})
        self.assertNotIn("other", {option["code"] for option in options})

    def test_every_approved_relation_normalizes_to_its_canonical_code(self) -> None:
        for relation in QualifierRelation:
            with self.subTest(relation=relation.value):
                is_self, code, label = normalize_qualifier_choice(
                    is_self=False,
                    relation_code=f"  {relation.value.upper()}  ",
                )
                self.assertFalse(is_self)
                self.assertEqual(code, relation.value)
                self.assertTrue(label)

    def test_self_is_a_separate_exclusive_path(self) -> None:
        self.assertEqual(
            normalize_qualifier_choice(is_self=True, relation_code=None),
            (True, None, "Self"),
        )
        with self.assertRaises(ValidationError):
            normalize_qualifier_choice(
                is_self=True,
                relation_code="spouse",
            )

    def test_missing_friend_and_arbitrary_relations_are_rejected(self) -> None:
        for relation in (None, "Friend", "Colleague", "Acquaintance", "Cousin"):
            with self.subTest(relation=relation):
                with self.assertRaises(ValidationError):
                    normalize_qualifier_choice(
                        is_self=False,
                        relation_code=relation,
                    )

    def test_selection_token_is_hashed_and_length_checked(self) -> None:
        token = "a" * 43
        digest = hash_qualifier_selection_token(token)

        self.assertEqual(len(digest), 64)
        self.assertNotIn(token, digest)
        self.assertEqual(digest, hash_qualifier_selection_token(token))
        with self.assertRaises(ValidationError):
            hash_qualifier_selection_token("short")


if __name__ == "__main__":
    unittest.main()
