from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    AgencyModel,
    Base,
    ClientGroupModel,
    PassportSubmissionModel,
    QualifierSelectionModel,
)


class QualifierPersistenceConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.agency_id = uuid.uuid4()
        self.group_id = uuid.uuid4()
        self.selected_at = datetime.now(tz=UTC)
        with Session(self.engine) as session:
            session.add(
                AgencyModel(
                    id=self.agency_id,
                    name="Qualifier Agency",
                    email=f"{self.agency_id}@example.com",
                )
            )
            session.add(
                ClientGroupModel(
                    id=self.group_id,
                    name="Qualifier Group",
                    token="q" * 43,
                    agency_id=self.agency_id,
                    status="active",
                    created_by_user_id=None,
                    relation_with_qualifier_enabled=True,
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def _selection(self, **overrides) -> QualifierSelectionModel:
        values = {
            "id": uuid.uuid4(),
            "group_id": self.group_id,
            "token_hash": uuid.uuid4().hex * 2,
            "is_self": False,
            "relation_code": "spouse",
            "relation_label": "Spouse",
            "selected_at": self.selected_at,
            "expires_at": self.selected_at + timedelta(hours=1),
            "created_at": self.selected_at,
        }
        values.update(overrides)
        return QualifierSelectionModel(**values)

    def _submission(
        self,
        selection: QualifierSelectionModel,
    ) -> PassportSubmissionModel:
        return PassportSubmissionModel(
            group_id=self.group_id,
            agency_id=self.agency_id,
            client_name="Traveller",
            image_s3_key=f"drafts/{uuid.uuid4()}.jpg",
            qualifier_enabled_snapshot=True,
            qualifier_selection_id=selection.id,
            qualifier_is_self=selection.is_self,
            qualifier_relation_code=selection.relation_code,
            qualifier_relation_label=selection.relation_label,
            qualifier_selected_at=selection.selected_at,
        )

    def test_valid_selection_and_snapshot_persist(self) -> None:
        selection = self._selection()
        with Session(self.engine) as session:
            session.add(selection)
            session.flush()
            session.add(self._submission(selection))
            session.commit()

    def test_database_rejects_friend_and_nonexclusive_snapshot(self) -> None:
        with Session(self.engine) as session:
            session.add(
                self._selection(
                    relation_code="friend",
                    relation_label="Friend",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

        selection = self._selection()
        with Session(self.engine) as session:
            session.add(selection)
            session.flush()
            invalid = self._submission(selection)
            invalid.qualifier_is_self = True
            with self.assertRaises(IntegrityError):
                session.add(invalid)
                session.commit()

        selection = self._selection(is_self=True, relation_code=None, relation_label="Self")
        with Session(self.engine) as session:
            session.add(selection)
            session.flush()
            invalid_label = self._submission(selection)
            invalid_label.qualifier_relation_label = "Spouse"
            with self.assertRaises(IntegrityError):
                session.add(invalid_label)
                session.commit()

    def test_one_selection_cannot_be_associated_with_two_submissions(self) -> None:
        selection = self._selection()
        selection_id = selection.id
        with Session(self.engine) as session:
            session.add(selection)
            session.flush()
            session.add(self._submission(selection))
            session.commit()

        with Session(self.engine) as session:
            persisted = session.get(QualifierSelectionModel, selection_id)
            if persisted is None:
                raise AssertionError("selection was not persisted")
            session.add(self._submission(persisted))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_submission_cannot_reference_selection_from_another_group(self) -> None:
        other_group_id = uuid.uuid4()
        selection = self._selection()
        with Session(self.engine) as session:
            session.add(
                ClientGroupModel(
                    id=other_group_id,
                    name="Other Qualifier Group",
                    token="o" * 43,
                    agency_id=self.agency_id,
                    status="active",
                    created_by_user_id=None,
                    relation_with_qualifier_enabled=True,
                )
            )
            session.add(selection)
            session.flush()
            mismatched = self._submission(selection)
            mismatched.group_id = other_group_id
            with self.assertRaises(IntegrityError):
                session.add(mismatched)
                session.commit()


if __name__ == "__main__":
    unittest.main()
