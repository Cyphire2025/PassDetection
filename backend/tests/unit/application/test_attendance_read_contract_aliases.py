"""Attendance read contracts keep legacy identity, introspection and serialization."""

from __future__ import annotations

import dataclasses
import pickle
import uuid
from typing import get_type_hints

from app.application import attendance_closeout_read_contracts, attendance_read_contracts
from app.infrastructure.repositories import (
    attendance_closeout_types,
    attendance_dashboard_repository,
)
from tests.unit.application.test_attendance_dashboard import _aggregate, _closeout_status


def test_shared_read_contracts_preserve_single_identity_pickle_and_type_resolution():
    group = _aggregate()
    closeout = _closeout_status()
    missing = attendance_dashboard_repository.MissingPassengerProjection(uuid.uuid4(), "Synthetic")
    instances = [
        group,
        group.roster,
        group.activities[0],
        attendance_dashboard_repository.AttendanceCoordinatorScanAggregate(
            uuid.uuid4(), uuid.uuid4(), 3
        ),
        missing,
        attendance_dashboard_repository.MissingPassengerPage((missing,), False, None),
        closeout,
        closeout.coordinators[0],
    ]
    assert len({type(item) for item in instances}) == 8
    for item in instances:
        kind = type(item)
        closeout_value = kind.__name__.startswith("AttendanceCloseout")
        contracts = (
            attendance_closeout_read_contracts if closeout_value else attendance_read_contracts
        )
        original = attendance_closeout_types if closeout_value else attendance_dashboard_repository
        assert kind is getattr(contracts, kind.__name__) is getattr(original, kind.__name__)
        assert kind.__module__ == original.__name__
        assert pickle.loads(pickle.dumps(item)) == item
        assert set(get_type_hints(kind)) == {field.name for field in dataclasses.fields(kind)}
        assert kind.__dataclass_params__.frozen and not hasattr(item, "__dict__")
