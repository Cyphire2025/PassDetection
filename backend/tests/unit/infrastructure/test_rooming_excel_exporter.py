from __future__ import annotations

import io
import uuid
from datetime import date
from types import SimpleNamespace

from openpyxl import load_workbook

from app.infrastructure.export.rooming_excel_exporter import RoomingExcelExporter


def test_rooming_export_has_exact_guest_order_values_vip_style_and_formula_safety() -> None:
    passenger_id = uuid.uuid4()
    group = SimpleNamespace(
        name="=Unsafe Group",
        staff_code_enabled=True,
        agent_employee_code_enabled=True,
        travel_date=date(2026, 8, 1),
    )
    hotel = SimpleNamespace(
        hotel_name="+Unsafe Hotel",
        city="@Unsafe City",
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 3),
    )
    room = SimpleNamespace(room_number="-1", room_type="single")
    assignment = SimpleNamespace(passenger_id=passenger_id)
    passenger = SimpleNamespace(
        id=passenger_id,
        confirmed_fields={
            "staff_code": "42",
            "agent_employee_type": "employee",
            "agent_employee_code": "7",
            "given_names": "-Formula Given",
            "surname": "Tester",
            "sex": "F",
            "passport_number": "=P123",
            "date_of_birth": "2000-01-02",
            "date_of_issue": "2020-02-03",
            "date_of_expiry": "2030-02-03",
            "place_of_issue": "@Delhi",
        },
        extracted_fields={},
        staff_metadata={},
    )
    content = RoomingExcelExporter().export_hotel(
        group=group,
        hotel=hotel,
        rooms=[(room, [assignment])],
        passenger_by_id={passenger_id: passenger},
        vip_passenger_ids={passenger_id},
        priority_fields=[
            {"key": "whatsapp:department", "label": "Department", "source": "whatsapp"},
            {"key": "custom:zone", "label": "Zone", "source": "custom_question"},
        ],
        priority_values={
            passenger_id: {
                "whatsapp:department": "=Finance",
                "custom:zone": "North",
            }
        },
    )
    worksheet = load_workbook(io.BytesIO(content)).active
    headers = [cell.value for cell in worksheet[6]]

    assert headers == [
        "Room Number",
        "Room Type",
        "VIP",
        "Staff Code",
        "Agent/Employee Code",
        "Department",
        "Zone",
        "Age Group",
        "GIVEN NAME",
        "SURNAME",
        "GENDER",
        "PASSPORT NUM",
        "DOB",
        "DOI",
        "DOE",
        "PLACE OF ISSUE",
    ]
    values = dict(zip(headers, (cell.value for cell in worksheet[7]), strict=True))
    assert values["Staff Code"] == "STF_42"
    assert values["Agent/Employee Code"] == "EMP_7"
    assert values["Department"] == "'=Finance"
    assert values["Age Group"] == "Adult"
    assert values["GIVEN NAME"] == "'-FORMULA GIVEN"
    assert values["GENDER"] == "Female"
    assert values["PASSPORT NUM"] == "'=P123"
    assert values["PLACE OF ISSUE"] == "'@Delhi"
    assert worksheet["A1"].data_type != "f"
    assert worksheet["A2"].data_type != "f"
    assert worksheet["A3"].data_type != "f"
    assert all(cell.fill.fgColor.rgb == "00FDE68A" for cell in worksheet[7])


def test_checkin_export_sanitizes_all_external_string_cells() -> None:
    passenger = SimpleNamespace(
        room_number="=101",
        room_type="twin",
        passenger_name="+Guest",
        checked_in=True,
        key_issued=False,
        welcome_letter_issued=False,
        remarks="@SUM(A1:A2)",
        is_vip=True,
    )
    content = RoomingExcelExporter().export_checkins(
        group_name="-Group",
        hotel_name="=Hotel",
        passengers=[passenger],
    )
    worksheet = load_workbook(io.BytesIO(content)).active

    assert [cell.value for cell in worksheet[2]][:5] == [
        "'-Group",
        "'=Hotel",
        "'=101",
        "Twin",
        "'+Guest",
    ]
    assert worksheet["I2"].value == "'@SUM(A1:A2)"


def test_rooming_export_omits_code_columns_when_group_did_not_ask() -> None:
    passenger_id = uuid.uuid4()
    group = SimpleNamespace(
        name="No Codes",
        staff_code_enabled=False,
        agent_employee_code_enabled=False,
        travel_date=date(2026, 8, 1),
    )
    hotel = SimpleNamespace(
        hotel_name="Hotel",
        city=None,
        check_in_date=None,
        check_out_date=None,
    )
    room = SimpleNamespace(room_number="1", room_type="twin")
    assignment = SimpleNamespace(passenger_id=passenger_id)
    passenger = SimpleNamespace(
        id=passenger_id,
        confirmed_fields={"sex": "M"},
        extracted_fields={},
        staff_metadata={},
    )
    content = RoomingExcelExporter().export_hotel(
        group=group,
        hotel=hotel,
        rooms=[(room, [assignment])],
        passenger_by_id={passenger_id: passenger},
        vip_passenger_ids=set(),
        priority_fields=[],
        priority_values={passenger_id: {}},
    )
    headers = [cell.value for cell in load_workbook(io.BytesIO(content)).active[6]]

    assert "Staff Code" not in headers
    assert "Agent/Employee Code" not in headers
